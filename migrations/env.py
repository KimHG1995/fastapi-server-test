import asyncio
from logging.config import fileConfig
from typing import cast

from alembic import context
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.base import Base
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.products import models as product_models  # noqa: F401
from app.modules.users import models as user_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_settings() -> Settings:
    configured_settings = config.attributes.get("settings")
    if configured_settings is not None:
        return cast(Settings, configured_settings)
    return Settings()


def do_run_migrations(connection: Connection) -> None:
    schema = config.attributes.get("schema")
    if schema is not None:
        schema_name = cast(str, schema)
        connection.execute(text(f'SET search_path TO "{schema_name}"'))
        connection.dialect.default_schema_name = schema_name

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    settings = get_settings()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.database_url
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )

    async with connectable.begin() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_offline() -> None:
    settings = get_settings()
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
