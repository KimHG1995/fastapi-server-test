from typing import Literal
from uuid import UUID

import pytest
from pytest import MonkeyPatch
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

import app.modules.auth.service as auth_service_module
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import AuthService
from app.modules.users.models import User, UserRole


class _CapturingAuthRepository(AuthRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.locked_state: tuple[bool, str] | None = None

    async def get_user_for_update(self, user_id: UUID) -> User | None:
        user = await super().get_user_for_update(user_id)
        if user is not None:
            self.locked_state = (user.is_active, user.password_hash)
        return user


@pytest.mark.parametrize("changed_state", ["inactive", "password_changed"])
async def test_login_reloads_authentication_state_before_issuing_tokens(
    migrated_database: AsyncEngine,
    test_settings: Settings,
    monkeypatch: MonkeyPatch,
    changed_state: Literal["inactive", "password_changed"],
) -> None:
    original_hash = hash_password("correct-horse-battery-staple")
    replacement_hash = hash_password("replacement-password")
    session_factory = async_sessionmaker(migrated_database, expire_on_commit=False)

    async with session_factory() as setup_session:
        async with setup_session.begin():
            user = User(
                email=f"{changed_state}@example.com",
                password_hash=original_hash,
                display_name="Learner",
                role=UserRole.USER,
                is_active=True,
            )
            setup_session.add(user)
            await setup_session.flush()
            user_id = user.id

    async with (
        session_factory() as authentication_session,
        session_factory() as concurrent_session,
    ):
        repository = _CapturingAuthRepository(authentication_session)
        service = AuthService(
            authentication_session,
            test_settings,
            repository=repository,
        )

        async def mutate_state_during_password_verification(
            password: str,
            password_hash: str,
        ) -> bool:
            assert password == "correct-horse-battery-staple"  # noqa: S105
            assert password_hash == original_hash
            async with concurrent_session.begin():
                concurrent_user = await concurrent_session.get(User, user_id)
                assert concurrent_user is not None
                if changed_state == "inactive":
                    concurrent_user.is_active = False
                else:
                    concurrent_user.password_hash = replacement_hash
            return True

        monkeypatch.setattr(
            auth_service_module,
            "verify_password_async",
            mutate_state_during_password_verification,
        )

        with pytest.raises(AppError) as raised:
            await service.login(
                LoginRequest(
                    email=f"{changed_state}@example.com",
                    password="correct-horse-battery-staple",  # noqa: S106
                )
            )

        assert raised.value.code == "INVALID_CREDENTIALS"
        assert raised.value.status_code == 401
        expected_state = (
            (False, original_hash) if changed_state == "inactive" else (True, replacement_hash)
        )
        assert repository.locked_state == expected_state

    async with session_factory() as assertion_session:
        refresh_count = await assertion_session.scalar(
            select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == user_id)
        )

    assert refresh_count == 0
