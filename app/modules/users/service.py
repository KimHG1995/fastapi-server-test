from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import (
    AuthenticationError,
    hash_password_async,
    verify_password_async,
)
from app.modules.auth.repository import AuthRepository
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import (
    ChangePasswordRequest,
    UpdateProfileRequest,
    UserRead,
)


class InvalidCurrentPasswordError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="INVALID_CURRENT_PASSWORD",
            status_code=400,
            title="Bad Request",
            detail="Current password is invalid.",
            type_slug="invalid-current-password",
        )


class PasswordReuseNotAllowedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="PASSWORD_REUSE_NOT_ALLOWED",
            status_code=400,
            title="Bad Request",
            detail="New password must differ from the current password.",
            type_slug="password-reuse-not-allowed",
        )


class UserService:
    def __init__(
        self,
        session: AsyncSession,
        repository: UserRepository | None = None,
        auth_repository: AuthRepository | None = None,
    ) -> None:
        self._session = session
        self._repository = repository or UserRepository(session)
        self._auth_repository = auth_repository or AuthRepository(session)

    def get_current(self, current_user: User) -> UserRead:
        return UserRead.model_validate(current_user)

    async def update_profile(
        self,
        user_id: UUID,
        request: UpdateProfileRequest,
    ) -> UserRead:
        try:
            current_user = await self._repository.get_for_update(user_id)
            if current_user is None or not current_user.is_active:
                raise AuthenticationError
            current_user.display_name = request.display_name
            await self._session.flush()
            await self._session.refresh(current_user)
            result = UserRead.model_validate(current_user)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return result

    async def change_password(
        self,
        current_user: User,
        request: ChangePasswordRequest,
    ) -> None:
        user_id = current_user.id
        password_hash = current_user.password_hash
        was_active = current_user.is_active

        await self._session.rollback()

        current_matches = await verify_password_async(
            request.current_password,
            password_hash,
        )
        if not current_matches or not was_active:
            raise InvalidCurrentPasswordError

        reuses_current = await verify_password_async(
            request.new_password,
            password_hash,
        )
        if reuses_current:
            raise PasswordReuseNotAllowedError

        new_password_hash = await hash_password_async(request.new_password)

        async with self._session.begin():
            locked_user = await self._repository.get_for_update(user_id)
            if (
                locked_user is None
                or not locked_user.is_active
                or locked_user.password_hash != password_hash
            ):
                raise AuthenticationError
            locked_user.password_hash = new_password_hash
            await self._auth_repository.revoke_all_for_user(
                user_id,
                datetime.now(UTC),
            )
