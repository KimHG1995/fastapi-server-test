import pytest
from pydantic import SecretStr

from app.core.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://app:app@localhost:5432/app",
        JWT_SECRET=SecretStr("x" * 32),
    )
