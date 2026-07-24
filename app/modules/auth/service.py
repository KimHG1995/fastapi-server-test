from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    AuthenticationError,
    create_access_token,
    generate_refresh_token,
    hash_password_async,
    hash_refresh_token,
    verify_password_async,
)
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import (
    LoginRequest,
    LogoutResult,
    RefreshTokenRequest,
    RegisterRequest,
    TokenPair,
)
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import UserRead


class EmailAlreadyExistsError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="EMAIL_ALREADY_EXISTS",
            status_code=409,
            title="Conflict",
            detail="An account with this email already exists.",
            type_slug="email-already-exists",
        )


class InvalidCredentialsError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="INVALID_CREDENTIALS",
            status_code=401,
            title="Unauthorized",
            detail="Email or password is invalid.",
            type_slug="invalid-credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


class InvalidRefreshTokenError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="INVALID_REFRESH_TOKEN",
            status_code=401,
            title="Unauthorized",
            detail="Refresh token is invalid or expired.",
            type_slug="invalid-refresh-token",
        )


class RefreshTokenReusedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="REFRESH_TOKEN_REUSED",
            status_code=401,
            title="Unauthorized",
            detail="Refresh token reuse was detected.",
            type_slug="refresh-token-reused",
        )


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        repository: AuthRepository | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._repository = repository or AuthRepository(session)

    async def register(self, request: RegisterRequest) -> UserRead:
        email = str(request.email).strip().lower()
        password_hash = await hash_password_async(request.password)
        try:
            async with self._session.begin():
                if await self._repository.get_user_by_email(email) is not None:
                    raise EmailAlreadyExistsError
                user = User(
                    email=email,
                    password_hash=password_hash,
                    display_name=request.display_name,
                    role=UserRole.USER,
                    is_active=True,
                )
                await self._repository.add_user(user)
                return UserRead.model_validate(user)
        except IntegrityError as exc:
            raise EmailAlreadyExistsError from exc

    async def login(self, request: LoginRequest) -> TokenPair:
        email = str(request.email).strip().lower()
        async with self._session.begin():
            user = await self._repository.get_user_by_email(email)
            authentication_snapshot = (
                None if user is None else (user.id, user.password_hash, user.is_active)
            )

        if authentication_snapshot is None:
            await verify_password_async(request.password, DUMMY_PASSWORD_HASH)
            raise InvalidCredentialsError

        user_id, password_hash, was_active = authentication_snapshot
        password_matches = await verify_password_async(request.password, password_hash)
        if not password_matches or not was_active:
            raise InvalidCredentialsError

        async with self._session.begin():
            current_user = await self._repository.get_user_for_update(user_id)
            if (
                current_user is None
                or not current_user.is_active
                or current_user.password_hash != password_hash
            ):
                raise InvalidCredentialsError
            now = datetime.now(UTC)
            raw_refresh_token = generate_refresh_token()
            refresh_token = RefreshToken(
                user_id=current_user.id,
                token_hash=hash_refresh_token(raw_refresh_token),
                expires_at=now + timedelta(days=self._settings.refresh_token_ttl_days),
            )
            await self._repository.add_refresh_token(refresh_token)
            access_token = create_access_token(current_user, self._settings, now=now)
            return TokenPair(
                access_token=access_token,
                refresh_token=raw_refresh_token,
                expires_in=self._settings.access_token_ttl_minutes * 60,
            )

    async def refresh(self, request: RefreshTokenRequest) -> TokenPair:
        token_hash = hash_refresh_token(request.refresh_token)
        reused = False
        token_pair: TokenPair | None = None

        async with self._session.begin():
            user, current = await self._lock_refresh_owner_and_token(token_hash)
            now = datetime.now(UTC)
            if current.expires_at <= now or not user.is_active:
                raise InvalidRefreshTokenError

            if current.revoked_at is not None:
                await self._repository.revoke_family(current.family_id, now)
                reused = True
            else:
                raw_replacement = generate_refresh_token()
                replacement = RefreshToken(
                    user_id=current.user_id,
                    family_id=current.family_id,
                    token_hash=hash_refresh_token(raw_replacement),
                    expires_at=now + timedelta(days=self._settings.refresh_token_ttl_days),
                )
                await self._repository.add_refresh_token(replacement)
                current.revoked_at = now
                current.replaced_by_id = replacement.id
                token_pair = TokenPair(
                    access_token=create_access_token(user, self._settings, now=now),
                    refresh_token=raw_replacement,
                    expires_in=self._settings.access_token_ttl_minutes * 60,
                )

        if reused:
            raise RefreshTokenReusedError
        if token_pair is None:
            raise RuntimeError("Refresh rotation completed without a token pair")
        return token_pair

    async def logout(self, request: RefreshTokenRequest) -> LogoutResult:
        token_hash = hash_refresh_token(request.refresh_token)
        async with self._session.begin():
            _, current = await self._lock_refresh_owner_and_token(token_hash)
            if current.revoked_at is None:
                current.revoked_at = datetime.now(UTC)
        return LogoutResult()

    async def logout_all(self, user_id: UUID) -> LogoutResult:
        now = datetime.now(UTC)
        try:
            user = await self._repository.get_user_for_update(user_id)
            if user is None or not user.is_active:
                raise AuthenticationError
            await self._repository.revoke_all_for_user(user_id, now)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return LogoutResult()

    async def _lock_refresh_owner_and_token(
        self,
        token_hash: str,
    ) -> tuple[User, RefreshToken]:
        identity = await self._repository.get_refresh_identity(token_hash)
        if identity is None:
            raise InvalidRefreshTokenError
        expected_user_id, expected_family_id = identity

        user = await self._repository.get_user_for_update(expected_user_id)
        current = await self._repository.get_refresh_for_update(token_hash)
        if (
            user is None
            or current is None
            or current.user_id != expected_user_id
            or current.family_id != expected_family_id
        ):
            raise InvalidRefreshTokenError
        return user, current
