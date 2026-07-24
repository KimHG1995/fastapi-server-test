from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_baseline_migration_creates_exact_expected_tables(
    migrated_database: AsyncEngine,
) -> None:
    async with migrated_database.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
        )

    assert table_names == {
        "alembic_version",
        "products",
        "refresh_tokens",
        "users",
    }
