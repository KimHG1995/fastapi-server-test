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
from app.modules.auth.schemas import RefreshTokenRequest, TokenPair
from app.modules.auth.service import AuthService
from app.modules.users.models import User, UserRole


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
    start = asyncio.Event()

    async def attempt_refresh() -> TokenPair | AppError:
        async with session_factory() as session:
            await start.wait()
            try:
                return await AuthService(session, test_settings).refresh(
                    RefreshTokenRequest(refresh_token=raw_token)
                )
            except AppError as exc:
                return exc

    first = asyncio.create_task(attempt_refresh())
    second = asyncio.create_task(attempt_refresh())
    start.set()
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
