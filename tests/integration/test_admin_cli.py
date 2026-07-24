import getpass
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app import cli
from app.core.config import Settings
from app.core.security import verify_password_async
from app.modules.users.models import User, UserRole


class _DriverConstraintViolation(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__("driver constraint violation")
        self.constraint_name = constraint_name


def _integrity_error(constraint_name: str) -> IntegrityError:
    driver_error = _DriverConstraintViolation(constraint_name)
    adapter_error = RuntimeError("asyncpg adapter integrity error")
    adapter_error.__cause__ = driver_error
    return IntegrityError("insert", {}, adapter_error)


@pytest.fixture
def cli_sessionmaker(
    migrated_database: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(migrated_database, expire_on_commit=False)


@pytest.fixture
def configure_cli(
    monkeypatch: pytest.MonkeyPatch,
    cli_sessionmaker: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> None:
    cli_engine = AsyncMock()
    monkeypatch.setattr(cli, "get_settings", lambda: test_settings)
    monkeypatch.setattr(
        cli,
        "create_engine_and_sessionmaker",
        lambda settings: (cli_engine, cli_sessionmaker),
    )


@pytest.mark.usefixtures("configure_cli")
async def test_create_admin_normalizes_email_and_hashes_password(
    monkeypatch: pytest.MonkeyPatch,
    cli_sessionmaker: async_sessionmaker[AsyncSession],
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "correct-horse-battery-staple"  # noqa: S105
    monkeypatch.setattr(getpass, "getpass", lambda prompt: password)

    exit_code = await cli.async_main(
        ["create-admin", "--email", "  ADMIN@Example.COM ", "--display-name", "Admin"]
    )

    assert exit_code == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert password not in output.out
    assert "admin@example.com" in output.out
    async with cli_sessionmaker() as session:
        user = (
            await session.execute(select(User).where(User.email == "admin@example.com"))
        ).scalar_one()
    assert user.role is UserRole.ADMIN
    assert user.password_hash.startswith("$argon2")
    assert await verify_password_async(password, user.password_hash)


@pytest.mark.usefixtures("configure_cli")
async def test_create_admin_rejects_duplicate_before_insert(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "correct-horse-battery-staple")
    arguments = ["create-admin", "--email", "admin@example.com", "--display-name", "Admin"]

    assert await cli.async_main(arguments) == 0
    capsys.readouterr()
    assert await cli.async_main(arguments) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "already exists" in output.err


async def test_create_admin_rolls_back_race_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    engine = AsyncMock()
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.return_value = None
    session.commit.side_effect = _integrity_error("uq_users_email")

    class SessionContext:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *args: object) -> None:
            return None

    def session_factory() -> SessionContext:
        return SessionContext()

    monkeypatch.setattr(cli, "get_settings", lambda: test_settings)
    monkeypatch.setattr(
        cli,
        "create_engine_and_sessionmaker",
        lambda settings: (engine, session_factory),
    )
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "correct-horse-battery-staple")

    assert (
        await cli.async_main(
            ["create-admin", "--email", "admin@example.com", "--display-name", "Admin"]
        )
        == 1
    )
    session.commit.assert_awaited_once()
    session.rollback.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.parametrize(
    ("failure_stage", "constraint_name"),
    [
        ("select", "uq_users_email"),
        ("select", "fk_unrelated_constraint"),
        ("commit", "fk_unrelated_constraint"),
    ],
)
async def test_create_admin_propagates_non_email_integrity_error_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
    failure_stage: str,
    constraint_name: str,
) -> None:
    integrity_error = _integrity_error(constraint_name)
    engine = AsyncMock()
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.return_value = None
    if failure_stage == "select":
        session.scalar.side_effect = integrity_error
    else:
        session.commit.side_effect = integrity_error

    class SessionContext:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(cli, "get_settings", lambda: test_settings)
    monkeypatch.setattr(
        cli,
        "create_engine_and_sessionmaker",
        lambda settings: (engine, SessionContext),
    )

    with pytest.raises(IntegrityError) as raised:
        await cli.create_admin(
            "admin@example.com",
            "Admin",
            "correct-horse-battery-staple",
        )

    assert raised.value is integrity_error
    session.rollback.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    if failure_stage == "select":
        session.add.assert_not_called()
        session.commit.assert_not_awaited()


async def test_invalid_password_is_not_exposed_or_connected(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "too-short"  # noqa: S105
    connect = MagicMock(side_effect=AssertionError("database must not be opened"))
    monkeypatch.setattr(cli, "create_engine_and_sessionmaker", connect)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: password)

    assert (
        await cli.async_main(
            ["create-admin", "--email", "admin@example.com", "--display-name", "Admin"]
        )
        == 1
    )

    output = capsys.readouterr()
    assert password not in output.out
    assert password not in output.err
    connect.assert_not_called()
