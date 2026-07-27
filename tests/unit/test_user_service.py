from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from types import TracebackType
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.users.service as user_service_module
from app.core.errors import AppError
from app.modules.auth.repository import AuthRepository
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import ChangePasswordRequest, UpdateProfileRequest
from app.modules.users.service import UserService


class _Transaction(AbstractAsyncContextManager[None]):
    def __init__(self, session: "_Session") -> None:
        self._session = session
        self._original_password_hash: str | None = None

    async def __aenter__(self) -> None:
        self._session.transaction_active = True
        self._original_password_hash = self._session.user.password_hash
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None and self._original_password_hash is not None:
            self._session.user.password_hash = self._original_password_hash
            self._session.rollbacks += 1
        self._session.transaction_active = False
        return None


class _Session:
    def __init__(self, user: User) -> None:
        self.user = user
        self.transaction_active = True
        self.transactions = 0
        self.rollbacks = 0
        self.commits = 0
        self.flushes = 0
        self.refreshed_users: list[User] = []

    async def commit(self) -> None:
        self.transaction_active = False
        self.commits += 1

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, user: User) -> None:
        self.refreshed_users.append(user)

    async def rollback(self) -> None:
        self.transaction_active = False
        self.rollbacks += 1

    def begin(self) -> _Transaction:
        self.transactions += 1
        return _Transaction(self)


class _UserRepository:
    def __init__(self, session: _Session, locked_user: User | None = None) -> None:
        self._session = session
        self._locked_user = locked_user if locked_user is not None else session.user
        self.locked_user_ids: list[UUID] = []

    async def get_for_update(self, user_id: UUID) -> User | None:
        self.locked_user_ids.append(user_id)
        assert self._session.transaction_active
        return self._locked_user


class _AuthRepository:
    def __init__(self, session: _Session, *, fail_revoke: bool = False) -> None:
        self._session = session
        self._fail_revoke = fail_revoke
        self.revoked_user_ids: list[UUID] = []

    async def revoke_all_for_user(self, user_id: UUID, revoked_at: datetime) -> None:
        del revoked_at
        assert self._session.transaction_active
        self.revoked_user_ids.append(user_id)
        if self._fail_revoke:
            raise RuntimeError("refresh revocation failed")


def _user(
    *,
    password_hash: str = "stored-password-hash",  # noqa: S107
    is_active: bool = True,
) -> User:
    now = datetime.now(UTC)
    return User(
        id=UUID("7651eb06-9052-481a-bcf2-33ab8b1d4ac8"),
        email="learner@example.com",
        password_hash=password_hash,
        display_name="Learner",
        role=UserRole.USER,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _service(
    user: User,
    *,
    locked_user: User | None = None,
    fail_revoke: bool = False,
) -> tuple[UserService, _Session, _UserRepository, _AuthRepository]:
    session = _Session(user)
    user_repository = _UserRepository(session, locked_user)
    auth_repository = _AuthRepository(session, fail_revoke=fail_revoke)
    service = UserService(
        cast(AsyncSession, session),
        repository=cast(UserRepository, user_repository),
        auth_repository=cast(AuthRepository, auth_repository),
    )
    return service, session, user_repository, auth_repository


@pytest.mark.parametrize("field", ["email", "role", "is_active"])
def test_update_profile_rejects_privileged_or_identity_fields(field: str) -> None:
    with pytest.raises(ValidationError) as raised:
        UpdateProfileRequest.model_validate({"display_name": "New Name", field: "not-allowed"})

    assert any(error["type"] == "extra_forbidden" for error in raised.value.errors())


async def test_get_current_returns_public_user_shape() -> None:
    user = _user()
    service, _, _, _ = _service(user)

    result = service.get_current(user)

    assert result.id == user.id
    assert result.email == user.email
    assert result.display_name == "Learner"
    assert not hasattr(result, "password_hash")


async def test_update_profile_trims_display_name() -> None:
    user = _user()
    service, session, repository, _ = _service(user)

    result = await service.update_profile(
        user.id,
        UpdateProfileRequest(display_name="  New Name  "),
    )

    assert result.display_name == "New Name"
    assert user.display_name == "New Name"
    assert repository.locked_user_ids == [user.id]
    assert session.transactions == 0
    assert session.flushes == 1
    assert session.refreshed_users == [user]
    assert session.commits == 1


async def test_change_password_rejects_wrong_current_password(
    monkeypatch: MonkeyPatch,
) -> None:
    user = _user()
    service, session, repository, auth_repository = _service(user)
    transaction_states: list[bool] = []

    async def reject_password(password: str, password_hash: str) -> bool:
        assert password == "wrong-current-password"  # noqa: S105
        assert password_hash == "stored-password-hash"  # noqa: S105
        transaction_states.append(session.transaction_active)
        return False

    monkeypatch.setattr(user_service_module, "verify_password_async", reject_password)

    with pytest.raises(AppError) as raised:
        await service.change_password(
            user,
            ChangePasswordRequest(
                current_password="wrong-current-password",  # noqa: S106
                new_password="new-secure-password",  # noqa: S106
            ),
        )

    assert raised.value.code == "INVALID_CURRENT_PASSWORD"
    assert raised.value.status_code == 400
    assert transaction_states == [False]
    assert repository.locked_user_ids == []
    assert auth_repository.revoked_user_ids == []


async def test_change_password_rejects_reusing_current_password(
    monkeypatch: MonkeyPatch,
) -> None:
    user = _user()
    service, session, repository, auth_repository = _service(user)
    verification_states: list[bool] = []
    hash_calls: list[str] = []

    async def accept_password(password: str, password_hash: str) -> bool:
        del password, password_hash
        verification_states.append(session.transaction_active)
        return True

    async def capture_hash(password: str) -> str:
        hash_calls.append(password)
        return "new-password-hash"

    monkeypatch.setattr(user_service_module, "verify_password_async", accept_password)
    monkeypatch.setattr(user_service_module, "hash_password_async", capture_hash)

    with pytest.raises(AppError) as raised:
        await service.change_password(
            user,
            ChangePasswordRequest(
                current_password="current-secure-password",  # noqa: S106
                new_password="current-secure-password",  # noqa: S106
            ),
        )

    assert raised.value.code == "PASSWORD_REUSE_NOT_ALLOWED"
    assert raised.value.status_code == 400
    assert verification_states == [False, False]
    assert hash_calls == []
    assert repository.locked_user_ids == []
    assert auth_repository.revoked_user_ids == []


async def test_change_password_hashes_outside_transaction_then_updates_and_revokes(
    monkeypatch: MonkeyPatch,
) -> None:
    user = _user()
    service, session, repository, auth_repository = _service(user)
    work_states: list[tuple[str, bool]] = []

    async def verify_password(password: str, password_hash: str) -> bool:
        del password, password_hash
        work_states.append(("verify", session.transaction_active))
        return len(work_states) == 1

    async def hash_password(password: str) -> str:
        assert password == "new-secure-password"  # noqa: S105
        work_states.append(("hash", session.transaction_active))
        return "new-password-hash"

    monkeypatch.setattr(user_service_module, "verify_password_async", verify_password)
    monkeypatch.setattr(user_service_module, "hash_password_async", hash_password)

    await service.change_password(
        user,
        ChangePasswordRequest(
            current_password="current-secure-password",  # noqa: S106
            new_password="new-secure-password",  # noqa: S106
        ),
    )

    assert work_states == [
        ("verify", False),
        ("verify", False),
        ("hash", False),
    ]
    assert session.transactions == 1
    assert repository.locked_user_ids == [user.id]
    assert user.password_hash == "new-password-hash"  # noqa: S105
    assert auth_repository.revoked_user_ids == [user.id]


@pytest.mark.parametrize("changed_state", ["inactive", "password_changed"])
async def test_change_password_rejects_changed_user_state_after_verification(
    monkeypatch: MonkeyPatch,
    changed_state: str,
) -> None:
    user = _user()
    locked_user = _user(
        password_hash=(
            "concurrently-changed-hash"
            if changed_state == "password_changed"
            else user.password_hash
        ),
        is_active=changed_state != "inactive",
    )
    service, session, repository, auth_repository = _service(
        user,
        locked_user=locked_user,
    )

    async def verify_password(password: str, password_hash: str) -> bool:
        del password_hash
        assert not session.transaction_active
        return False if password == "new-secure-password" else True  # noqa: S105

    async def hash_password(password: str) -> str:
        del password
        assert not session.transaction_active
        return "new-password-hash"

    monkeypatch.setattr(user_service_module, "verify_password_async", verify_password)
    monkeypatch.setattr(user_service_module, "hash_password_async", hash_password)

    with pytest.raises(AppError) as raised:
        await service.change_password(
            user,
            ChangePasswordRequest(
                current_password="current-secure-password",  # noqa: S106
                new_password="new-secure-password",  # noqa: S106
            ),
        )

    assert raised.value.code == "INVALID_ACCESS_TOKEN"
    assert repository.locked_user_ids == [user.id]
    assert locked_user.password_hash != "new-password-hash"  # noqa: S105
    assert auth_repository.revoked_user_ids == []


async def test_change_password_rolls_back_user_update_when_revocation_fails(
    monkeypatch: MonkeyPatch,
) -> None:
    user = _user()
    original_hash = user.password_hash
    service, session, _, auth_repository = _service(user, fail_revoke=True)

    async def verify_password(password: str, password_hash: str) -> bool:
        del password_hash
        return False if password == "new-secure-password" else True  # noqa: S105

    async def hash_password(password: str) -> str:
        del password
        return "new-password-hash"

    monkeypatch.setattr(user_service_module, "verify_password_async", verify_password)
    monkeypatch.setattr(user_service_module, "hash_password_async", hash_password)

    with pytest.raises(RuntimeError, match="refresh revocation failed"):
        await service.change_password(
            user,
            ChangePasswordRequest(
                current_password="current-secure-password",  # noqa: S106
                new_password="new-secure-password",  # noqa: S106
            ),
        )

    assert auth_repository.revoked_user_ids == [user.id]
    assert user.password_hash == original_hash
    assert session.rollbacks == 2
