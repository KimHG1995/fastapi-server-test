import asyncio
from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from app.core.config import Settings
from app.db.session import get_session
from app.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://app:app@localhost:5432/app",
        JWT_SECRET=SecretStr("x" * 32),
    )


@pytest.fixture(scope="session")
def postgresql_url() -> Iterator[str]:
    with PostgresContainer("postgres:18.4-trixie") as postgres:
        sync_url = make_url(postgres.get_connection_url())
        yield sync_url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


@pytest_asyncio.fixture
async def migrated_database(postgresql_url: str) -> AsyncIterator[AsyncEngine]:
    schema = f"test_{uuid4().hex}"
    administration_engine = create_async_engine(
        postgresql_url,
        isolation_level="AUTOCOMMIT",
    )

    async with administration_engine.connect() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL=postgresql_url,
        JWT_SECRET=SecretStr("x" * 32),
    )
    alembic_config = Config("alembic.ini")
    alembic_config.attributes["settings"] = settings
    alembic_config.attributes["schema"] = schema
    await asyncio.to_thread(command.upgrade, alembic_config, "head")

    engine = create_async_engine(
        postgresql_url,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        yield engine
    finally:
        await engine.dispose()
        async with administration_engine.connect() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await administration_engine.dispose()


@pytest_asyncio.fixture
async def db_session(migrated_database: AsyncEngine) -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(migrated_database, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(
    migrated_database: AsyncEngine,
    postgresql_url: str,
) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL=postgresql_url,
        JWT_SECRET=SecretStr("x" * 32),
    )
    app: FastAPI = create_app(settings)
    session_factory = async_sessionmaker(migrated_database, expire_on_commit=False)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()
