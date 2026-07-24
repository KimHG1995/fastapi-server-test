from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import cast
from uuid import UUID, uuid4

import pytest
from pytest import MonkeyPatch
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.auth.service as auth_service_module
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import DUMMY_PASSWORD_HASH, hash_password
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.auth.service import AuthService
from app.modules.users.models import User, UserRole


class _Transaction(AbstractAsyncContextManager[None]):
    def __init__(self, session: "_Session") -> None:
        self._session = session

    async def __aenter__(self) -> None:
        self._session.transaction_active = True
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._session.transaction_active = False
        return None


class _Session:
    def __init__(self) -> None:
        self.transactions = 0
        self.transaction_active = False

    def begin(self) -> _Transaction:
        self.transactions += 1
        return _Transaction(self)


class _Repository:
    def __init__(self, user: User | None = None) -> None:
        self.user = user
        self.added_users: list[User] = []
        self.added_refresh_tokens: list[RefreshToken] = []
        self.lookup_emails: list[str] = []

    async def get_user_by_email(self, email: str) -> User | None:
        self.lookup_emails.append(email)
        if self.user is not None and self.user.email == email:
            return self.user
        return None

    async def add_user(self, user: User) -> User:
        now = datetime.now(UTC)
        user.id = uuid4()
        user.created_at = now
        user.updated_at = now
        self.user = user
        self.added_users.append(user)
        return user

    async def add_refresh_token(self, refresh_token: RefreshToken) -> RefreshToken:
        self.added_refresh_tokens.append(refresh_token)
        return refresh_token


def _service(
    settings: Settings,
    repository: _Repository,
) -> tuple[AuthService, _Session]:
    session = _Session()
    service = AuthService(
        cast(AsyncSession, session),
        settings,
        repository=cast(AuthRepository, repository),
    )
    return service, session


def _user(
    *,
    email: str = "learner@example.com",
    password: str = "correct-horse-battery-staple",  # noqa: S107
    is_active: bool = True,
) -> User:
    now = datetime.now(UTC)
    return User(
        id=UUID("7651eb06-9052-481a-bcf2-33ab8b1d4ac8"),
        email=email,
        password_hash=hash_password(password),
        display_name="Learner",
        role=UserRole.USER,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


async def test_registration_normalizes_email_and_always_assigns_user(
    test_settings: Settings,
) -> None:
    repository = _Repository()
    service, session = _service(test_settings, repository)

    result = await service.register(
        RegisterRequest(
            email="  New.User@Example.COM  ",
            password="correct-horse-battery-staple",  # noqa: S106
            display_name=" New User ",
        )
    )

    assert repository.lookup_emails == ["new.user@example.com"]
    assert len(repository.added_users) == 1
    assert repository.added_users[0].email == "new.user@example.com"
    assert repository.added_users[0].role is UserRole.USER
    assert result.email == "new.user@example.com"
    assert result.display_name == "New User"
    assert session.transactions == 1


async def test_registration_hashes_password_before_opening_transaction(
    test_settings: Settings,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = _Repository()
    service, session = _service(test_settings, repository)
    transaction_states: list[bool] = []

    async def fake_hash_password_async(password: str) -> str:
        assert password == "correct-horse-battery-staple"  # noqa: S105
        transaction_states.append(session.transaction_active)
        return "offloaded-password-hash"

    monkeypatch.setattr(
        auth_service_module,
        "hash_password_async",
        fake_hash_password_async,
    )

    await service.register(
        RegisterRequest(
            email="learner@example.com",
            password="correct-horse-battery-staple",  # noqa: S106
            display_name="Learner",
        )
    )

    assert transaction_states == [False]
    assert repository.added_users[0].password_hash == "offloaded-password-hash"  # noqa: S105


async def test_duplicate_registration_raises_email_already_exists(
    test_settings: Settings,
) -> None:
    repository = _Repository(_user())
    service, _ = _service(test_settings, repository)

    with pytest.raises(AppError) as raised:
        await service.register(
            RegisterRequest(
                email="LEARNER@example.com",
                password="correct-horse-battery-staple",  # noqa: S106
                display_name="Learner",
            )
        )

    assert raised.value.code == "EMAIL_ALREADY_EXISTS"
    assert raised.value.status_code == 409


async def test_registration_integrity_race_maps_to_email_conflict(
    test_settings: Settings,
) -> None:
    class _RacingRepository(_Repository):
        async def add_user(self, user: User) -> User:
            del user
            raise IntegrityError("INSERT INTO users", {}, RuntimeError("duplicate"))

    service, _ = _service(test_settings, _RacingRepository())

    with pytest.raises(AppError) as raised:
        await service.register(
            RegisterRequest(
                email="learner@example.com",
                password="correct-horse-battery-staple",  # noqa: S106
                display_name="Learner",
            )
        )

    assert raised.value.code == "EMAIL_ALREADY_EXISTS"
    assert raised.value.status_code == 409


async def test_unknown_email_and_bad_password_return_same_error(
    test_settings: Settings,
) -> None:
    unknown_service, _ = _service(test_settings, _Repository())
    bad_password_service, _ = _service(test_settings, _Repository(_user()))

    with pytest.raises(AppError) as unknown:
        await unknown_service.login(
            LoginRequest(email="missing@example.com", password="wrong-password")  # noqa: S106
        )
    with pytest.raises(AppError) as bad_password:
        await bad_password_service.login(
            LoginRequest(email="learner@example.com", password="wrong-password")  # noqa: S106
        )

    assert (
        unknown.value.code,
        unknown.value.status_code,
        unknown.value.detail,
    ) == (
        bad_password.value.code,
        bad_password.value.status_code,
        bad_password.value.detail,
    )
    assert unknown.value.code == "INVALID_CREDENTIALS"
    assert unknown.value.status_code == 401


async def test_unknown_email_verifies_module_level_dummy_hash(
    test_settings: Settings,
    monkeypatch: MonkeyPatch,
) -> None:
    service, _ = _service(test_settings, _Repository())
    calls: list[tuple[str, str]] = []

    async def fake_verify_password_async(password: str, password_hash: str) -> bool:
        calls.append((password, password_hash))
        return False

    monkeypatch.setattr(
        auth_service_module,
        "verify_password_async",
        fake_verify_password_async,
    )

    with pytest.raises(AppError):
        await service.login(
            LoginRequest(email="missing@example.com", password="wrong-password")  # noqa: S106
        )

    assert calls == [("wrong-password", DUMMY_PASSWORD_HASH)]


async def test_inactive_user_cannot_log_in(test_settings: Settings) -> None:
    service, _ = _service(test_settings, _Repository(_user(is_active=False)))

    with pytest.raises(AppError) as raised:
        await service.login(
            LoginRequest(
                email="learner@example.com",
                password="correct-horse-battery-staple",  # noqa: S106
            )
        )

    assert raised.value.code == "INVALID_CREDENTIALS"
    assert raised.value.status_code == 401


async def test_successful_login_persists_only_refresh_token_hash(
    test_settings: Settings,
) -> None:
    repository = _Repository(_user())
    service, session = _service(test_settings, repository)

    result = await service.login(
        LoginRequest(
            email=" LEARNER@EXAMPLE.COM ",
            password="correct-horse-battery-staple",  # noqa: S106
        )
    )

    assert result.token_type == "bearer"  # noqa: S105
    assert result.expires_in == 15 * 60
    assert result.access_token
    assert result.refresh_token
    assert repository.lookup_emails == ["learner@example.com"]
    assert len(repository.added_refresh_tokens) == 1
    stored = repository.added_refresh_tokens[0]
    assert len(stored.token_hash) == 64
    assert stored.token_hash != result.refresh_token
    assert result.refresh_token not in repr(stored.__dict__)
    assert session.transactions == 1
