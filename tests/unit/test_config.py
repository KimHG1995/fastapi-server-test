from pydantic import SecretStr

from app.core.config import Settings


def test_settings_parse_comma_separated_cors_origins() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://app:app@localhost:5432/app",
        JWT_SECRET=SecretStr("x" * 32),
        CORS_ORIGINS="http://localhost:3000,http://localhost:5173",
    )

    assert settings.cors_origins == [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
