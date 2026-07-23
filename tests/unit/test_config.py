from pathlib import Path

from pydantic import SecretStr
from pytest import MonkeyPatch

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


def test_settings_load_uppercase_process_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5432/app")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("ACCESS_TOKEN_TTL_MINUTES", "20")
    monkeypatch.setenv("REFRESH_TOKEN_TTL_DAYS", "40")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.database_url == "postgresql+asyncpg://app:app@localhost:5432/app"
    assert settings.jwt_secret.get_secret_value() == "x" * 32
    assert settings.access_token_ttl_minutes == 20
    assert settings.refresh_token_ttl_days == 40
    assert settings.cors_origins == ["http://localhost:3000", "http://localhost:5173"]
    assert settings.log_level == "DEBUG"


def test_settings_load_uppercase_dotenv_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=test",
                "DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app",
                f"JWT_SECRET={'x' * 32}",
                "ACCESS_TOKEN_TTL_MINUTES=20",
                "REFRESH_TOKEN_TTL_DAYS=40",
                "CORS_ORIGINS=http://localhost:3000,http://localhost:5173",
                "LOG_LEVEL=DEBUG",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.app_env == "test"
    assert settings.database_url == "postgresql+asyncpg://app:app@localhost:5432/app"
    assert settings.jwt_secret.get_secret_value() == "x" * 32
    assert settings.access_token_ttl_minutes == 20
    assert settings.refresh_token_ttl_days == 40
    assert settings.cors_origins == ["http://localhost:3000", "http://localhost:5173"]
    assert settings.log_level == "DEBUG"
