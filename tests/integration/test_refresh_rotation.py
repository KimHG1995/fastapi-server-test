import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password, hash_refresh_token
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import RefreshTokenRequest, TokenPair
from app.modules.auth.service import AuthService
from app.modules.users.models import User, UserRole


class _PauseAfterRefreshAndUserLocks(AuthRepository):
    def __init__(
        self,
        session: AsyncSession,
        locks_acquired: asyncio.Event,
        release_locks: asyncio.Event,
    ) -> None:
        super().__init__(session)
        self._locks_acquired = locks_acquired
        self._release_locks = release_locks
        self._refresh_locked = False
        self._user_locked = False
        self._paused = False

    async def get_user_for_update(self, user_id: UUID) -> User | None:
        user = await super().get_user_for_update(user_id)
        self._user_locked = user is not None
        await self._pause_after_both_locks()
        return user

    async def get_refresh_for_update(self, token_hash: str) -> RefreshToken | None:
        refresh_token = await super().get_refresh_for_update(token_hash)
        self._refresh_locked = refresh_token is not None
        await self._pause_after_both_locks()
        return refresh_token

    async def _pause_after_both_locks(self) -> None:
        if self._user_locked and self._refresh_locked and not self._paused:
            self._paused = True
            self._locks_acquired.set()
            await self._release_locks.wait()


class _SignalLockAttempt(AuthRepository):
    def __init__(self, session: AsyncSession, lock_attempted: asyncio.Event) -> None:
        super().__init__(session)
        self._lock_attempted = lock_attempted

    async def get_user_for_update(self, user_id: UUID) -> User | None:
        self._lock_attempted.set()
        return await super().get_user_for_update(user_id)

    async def get_refresh_for_update(self, token_hash: str) -> RefreshToken | None:
        self._lock_attempted.set()
        return await super().get_refresh_for_update(token_hash)


class _PauseAfterReplacementInsert(AuthRepository):
    def __init__(
        self,
        session: AsyncSession,
        replacement_inserted: asyncio.Event,
        release_rotation: asyncio.Event,
    ) -> None:
        super().__init__(session)
        self._replacement_inserted = replacement_inserted
        self._release_rotation = release_rotation

    async def add_refresh_token(self, refresh_token: RefreshToken) -> RefreshToken:
        added = await super().add_refresh_token(refresh_token)
        self._replacement_inserted.set()
        await self._release_rotation.wait()
        return added


class _SignalReuseMutationBoundary(AuthRepository):
    def __init__(self, session: AsyncSession, boundary_reached: asyncio.Event) -> None:
        super().__init__(session)
        self._boundary_reached = boundary_reached

    async def get_user_for_update(self, user_id: UUID) -> User | None:
        self._boundary_reached.set()
        return await super().get_user_for_update(user_id)

    async def revoke_family(self, family_id: UUID, revoked_at: datetime) -> None:
        self._boundary_reached.set()
        await super().revoke_family(family_id, revoked_at)


async def _persist_refresh_token(
    session_factory: async_sessionmaker[AsyncSession],
    raw_token: str,
    *,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
    family_id: UUID | None = None,
) -> tuple[UUID, UUID]:
    async with session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{uuid4()}@example.com",
                password_hash=hash_password("correct-horse-battery-staple"),
                display_name="Learner",
                role=UserRole.USER,
                is_active=True,
            )
            session.add(user)
            await session.flush()
            refresh_token = RefreshToken(
                user_id=user.id,
                family_id=family_id or uuid4(),
                token_hash=hash_refresh_token(raw_token),
                expires_at=expires_at or datetime.now(UTC) + timedelta(days=30),
                revoked_at=revoked_at,
            )
            session.add(refresh_token)
            await session.flush()
            return user.id, refresh_token.id


async def test_refresh_rotates_token_and_persists_only_replacement_hash(
    migrated_database: AsyncEngine,
    test_settings: Settings,
) -> None:
    session_factory = async_sessionmaker(migrated_database, expire_on_commit=False)
    raw_token = "original-refresh-token"  # noqa: S105
    _, original_id = await _persist_refresh_token(session_factory, raw_token)

    async with session_factory() as session:
        pair = await AuthService(session, test_settings).refresh(
            RefreshTokenRequest(refresh_token=raw_token)
        )

    assert pair.access_token
    assert pair.refresh_token != raw_token
    assert pair.expires_in == 900

    async with session_factory() as session:
        original = await session.get(RefreshToken, original_id)
        assert original is not None
        assert original.revoked_at is not None
        assert original.replaced_by_id is not None
        replacement = await session.get(RefreshToken, original.replaced_by_id)
        assert replacement is not None
        assert replacement.family_id == original.family_id
        assert replacement.revoked_at is None
        assert replacement.token_hash == hash_refresh_token(pair.refresh_token)
        persisted_strings = [
            value
            for row in (original, replacement)
            for value in vars(row).values()
            if isinstance(value, str)
        ]

    assert all(pair.refresh_token not in value for value in persisted_strings)


async def test_reusing_rotated_token_revokes_every_token_in_family(
    migrated_database: AsyncEngine,
    test_settings: Settings,
) -> None:
    session_factory = async_sessionmaker(migrated_database, expire_on_commit=False)
    raw_token = "refresh-token-that-will-be-reused"  # noqa: S105
    _, original_id = await _persist_refresh_token(session_factory, raw_token)

    async with session_factory() as session:
        replacement_pair = await AuthService(session, test_settings).refresh(
            RefreshTokenRequest(refresh_token=raw_token)
        )

    async with session_factory() as session:
        with pytest.raises(AppError) as raised:
            await AuthService(session, test_settings).refresh(
                RefreshTokenRequest(refresh_token=raw_token)
            )

    assert raised.value.code == "REFRESH_TOKEN_REUSED"
    assert raised.value.status_code == 401

    async with session_factory() as session:
        original = await session.get(RefreshToken, original_id)
        assert original is not None
        family_rows = (
            await session.scalars(
                select(RefreshToken).where(RefreshToken.family_id == original.family_id)
            )
        ).all()

    assert len(family_rows) == 2
    assert all(row.revoked_at is not None for row in family_rows)
    assert all(row.token_hash != replacement_pair.refresh_token for row in family_rows)


@pytest.mark.parametrize(
    ("raw_token", "expires_at"),
    [
        ("expired-refresh-token", datetime.now(UTC) - timedelta(seconds=1)),
        ("unknown-refresh-token", None),
    ],
)
async def test_expired_and_unknown_refresh_tokens_fail_with_same_public_error(
    migrated_database: AsyncEngine,
    test_settings: Settings,
    raw_token: str,
    expires_at: datetime | None,
) -> None:
    session_factory = async_sessionmaker(migrated_database, expire_on_commit=False)
    if expires_at is not None:
        await _persist_refresh_token(
            session_factory,
            raw_token,
            expires_at=expires_at,
        )

    async with session_factory() as session:
        with pytest.raises(AppError) as raised:
            await AuthService(session, test_settings).refresh(
                RefreshTokenRequest(refresh_token=raw_token)
            )

    assert raised.value.code == "INVALID_REFRESH_TOKEN"
    assert raised.value.status_code == 401


async def test_two_concurrent_refresh_attempts_cannot_both_succeed(
    migrated_database: AsyncEngine,
    test_settings: Settings,
) -> None:
    session_factory = async_sessionmaker(migrated_database, expire_on_commit=False)
    raw_token = "concurrent-refresh-token"  # noqa: S105
    _, original_id = await _persist_refresh_token(session_factory, raw_token)
    locks_acquired = asyncio.Event()
    release_locks = asyncio.Event()
    second_lock_attempted = asyncio.Event()

    async with session_factory() as first_session, session_factory() as second_session:
        first_repository = _PauseAfterRefreshAndUserLocks(
            first_session,
            locks_acquired,
            release_locks,
        )
        second_repository = _SignalLockAttempt(second_session, second_lock_attempted)
        first_service = AuthService(
            first_session,
            test_settings,
            repository=first_repository,
        )
        second_service = AuthService(
            second_session,
            test_settings,
            repository=second_repository,
        )

        async def attempt_refresh(service: AuthService) -> TokenPair | AppError:
            try:
                return await service.refresh(RefreshTokenRequest(refresh_token=raw_token))
            except AppError as exc:
                return exc

        first = asyncio.create_task(attempt_refresh(first_service))
        await asyncio.wait_for(locks_acquired.wait(), timeout=5)
        second = asyncio.create_task(attempt_refresh(second_service))
        await asyncio.wait_for(second_lock_attempted.wait(), timeout=5)
        assert not first.done()
        assert not second.done()
        release_locks.set()
        results = await asyncio.gather(first, second)

    successes = [result for result in results if isinstance(result, TokenPair)]
    failures = [result for result in results if isinstance(result, AppError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].code == "REFRESH_TOKEN_REUSED"

    async with session_factory() as session:
        original = await session.get(RefreshToken, original_id)
        assert original is not None
        family_rows = (
            await session.scalars(
                select(RefreshToken).where(RefreshToken.family_id == original.family_id)
            )
        ).all()

    assert len(family_rows) == 2
    assert all(row.revoked_at is not None for row in family_rows)


async def test_reuse_racing_with_sibling_rotation_revokes_new_replacement(
    migrated_database: AsyncEngine,
    test_settings: Settings,
) -> None:
    session_factory = async_sessionmaker(migrated_database, expire_on_commit=False)
    family_id = uuid4()
    reused_raw = "already-revoked-family-token"
    active_raw = "active-family-token"
    now = datetime.now(UTC)

    async with session_factory() as setup_session:
        async with setup_session.begin():
            user = User(
                email="family-race@example.com",
                password_hash=hash_password("correct-horse-battery-staple"),
                display_name="Family Race",
                role=UserRole.USER,
                is_active=True,
            )
            setup_session.add(user)
            await setup_session.flush()
            setup_session.add_all(
                [
                    RefreshToken(
                        user_id=user.id,
                        family_id=family_id,
                        token_hash=hash_refresh_token(reused_raw),
                        expires_at=now + timedelta(days=30),
                        revoked_at=now,
                    ),
                    RefreshToken(
                        user_id=user.id,
                        family_id=family_id,
                        token_hash=hash_refresh_token(active_raw),
                        expires_at=now + timedelta(days=30),
                    ),
                ]
            )

    replacement_inserted = asyncio.Event()
    release_rotation = asyncio.Event()
    reuse_boundary_reached = asyncio.Event()
    async with session_factory() as rotation_session, session_factory() as reuse_session:
        rotation_service = AuthService(
            rotation_session,
            test_settings,
            repository=_PauseAfterReplacementInsert(
                rotation_session,
                replacement_inserted,
                release_rotation,
            ),
        )
        reuse_service = AuthService(
            reuse_session,
            test_settings,
            repository=_SignalReuseMutationBoundary(
                reuse_session,
                reuse_boundary_reached,
            ),
        )

        rotation = asyncio.create_task(
            rotation_service.refresh(RefreshTokenRequest(refresh_token=active_raw))
        )
        await asyncio.wait_for(replacement_inserted.wait(), timeout=5)
        reuse = asyncio.create_task(
            reuse_service.refresh(RefreshTokenRequest(refresh_token=reused_raw))
        )
        await asyncio.wait_for(reuse_boundary_reached.wait(), timeout=5)
        assert not rotation.done()
        assert not reuse.done()
        release_rotation.set()
        rotation_result, reuse_result = await asyncio.gather(
            rotation,
            reuse,
            return_exceptions=True,
        )

    assert isinstance(rotation_result, TokenPair)
    assert isinstance(reuse_result, AppError)
    assert reuse_result.code == "REFRESH_TOKEN_REUSED"

    async with session_factory() as assertion_session:
        family_rows = (
            await assertion_session.scalars(
                select(RefreshToken).where(RefreshToken.family_id == family_id)
            )
        ).all()

    assert len(family_rows) == 3
    assert all(row.revoked_at is not None for row in family_rows)
