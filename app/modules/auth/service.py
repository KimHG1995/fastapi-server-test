from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginRequest, RegisterRequest, TokenPair
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
        try:
            async with self._session.begin():
                if await self._repository.get_user_by_email(email) is not None:
                    raise EmailAlreadyExistsError
                user = User(
                    email=email,
                    password_hash=hash_password(request.password),
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
            if user is None:
                verify_password(request.password, DUMMY_PASSWORD_HASH)
                raise InvalidCredentialsError
            if not verify_password(request.password, user.password_hash) or not user.is_active:
                raise InvalidCredentialsError

            now = datetime.now(UTC)
            raw_refresh_token = generate_refresh_token()
            refresh_token = RefreshToken(
                user_id=user.id,
                token_hash=hash_refresh_token(raw_refresh_token),
                expires_at=now + timedelta(days=self._settings.refresh_token_ttl_days),
            )
            await self._repository.add_refresh_token(refresh_token)
            access_token = create_access_token(user, self._settings, now=now)
            return TokenPair(
                access_token=access_token,
                refresh_token=raw_refresh_token,
                expires_in=self._settings.access_token_ttl_minutes * 60,
            )
