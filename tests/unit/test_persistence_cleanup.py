import asyncio
import runpy
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import cast

import pytest
import sqlalchemy.ext.asyncio
from alembic import context as alembic_context
from sqlalchemy.ext.asyncio import AsyncEngine

import tests.conftest as conftest_module
from app.core.config import Settings


class FailingBeginContext:
    async def __aenter__(self) -> None:
        raise RuntimeError("connection failed")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        return None


class FailingAlembicEngine:
    def __init__(self) -> None:
        self.disposed = False

    def begin(self) -> FailingBeginContext:
        return FailingBeginContext()

    async def dispose(self) -> None:
        self.disposed = True


def test_async_alembic_disposes_engine_when_connection_fails(
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    engine = FailingAlembicEngine()
    config = SimpleNamespace(
        attributes={"settings": test_settings},
        config_file_name=None,
        config_ini_section="alembic",
        get_section=lambda section, default: {},
    )
    monkeypatch.setattr(alembic_context, "config", config, raising=False)
    monkeypatch.setattr(alembic_context, "is_offline_mode", lambda: False)
    monkeypatch.setattr(
        sqlalchemy.ext.asyncio,
        "async_engine_from_config",
        lambda *args, **kwargs: engine,
    )

    with pytest.raises(RuntimeError, match="connection failed"):
        runpy.run_path("migrations/env.py", run_name="test_migrations_env")

    assert engine.disposed


class RecordingConnection:
    def __init__(self, statements: list[str], fail_drop: bool = False) -> None:
        self.statements = statements
        self.fail_drop = fail_drop

    async def execute(self, statement: object) -> None:
        rendered = str(statement)
        self.statements.append(rendered)
        if self.fail_drop and rendered.startswith("DROP SCHEMA"):
            raise RuntimeError("schema drop failed")


class RecordingConnectionContext:
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> RecordingConnection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        return None


class RecordingEngine:
    def __init__(
        self,
        statements: list[str],
        *,
        fail_dispose: bool = False,
        fail_drop: bool = False,
    ) -> None:
        self.connection = RecordingConnection(statements, fail_drop)
        self.disposed = False
        self.fail_dispose = fail_dispose

    def connect(self) -> AbstractAsyncContextManager[RecordingConnection]:
        return RecordingConnectionContext(self.connection)

    async def dispose(self) -> None:
        self.disposed = True
        if self.fail_dispose:
            raise RuntimeError("test engine dispose failed")


def migrated_database_function() -> Callable[[str], AsyncIterator[AsyncEngine]]:
    fixture_function = conftest_module.migrated_database._fixture_function  # type: ignore[attr-defined]
    return cast(Callable[[str], AsyncIterator[AsyncEngine]], fixture_function)


async def fail_migration(function: Callable[..., object], *args: object) -> None:
    raise RuntimeError("migration failed")


async def test_migration_failure_cleans_up_isolated_schema_and_both_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []
    administration_engine = RecordingEngine(statements)
    test_engine = RecordingEngine(statements)
    engines = iter(
        [
            cast(AsyncEngine, administration_engine),
            cast(AsyncEngine, test_engine),
        ]
    )
    monkeypatch.setattr(
        conftest_module,
        "create_async_engine",
        lambda *args, **kwargs: next(engines),
    )
    monkeypatch.setattr(asyncio, "to_thread", fail_migration)
    fixture = migrated_database_function()("postgresql+asyncpg://test")

    with pytest.raises(RuntimeError, match="migration failed"):
        await anext(fixture)

    assert test_engine.disposed
    assert any(statement.startswith("DROP SCHEMA") for statement in statements)
    assert administration_engine.disposed


async def test_cleanup_continues_when_test_engine_disposal_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []
    administration_engine = RecordingEngine(statements)
    test_engine = RecordingEngine(statements, fail_dispose=True)
    engines = iter(
        [
            cast(AsyncEngine, administration_engine),
            cast(AsyncEngine, test_engine),
        ]
    )
    monkeypatch.setattr(
        conftest_module,
        "create_async_engine",
        lambda *args, **kwargs: next(engines),
    )
    monkeypatch.setattr(asyncio, "to_thread", fail_migration)
    fixture = migrated_database_function()("postgresql+asyncpg://test")

    with pytest.raises(RuntimeError, match="test engine dispose failed"):
        await anext(fixture)

    assert any(statement.startswith("DROP SCHEMA") for statement in statements)
    assert administration_engine.disposed
