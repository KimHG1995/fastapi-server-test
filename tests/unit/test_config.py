import warnings
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from pytest import MonkeyPatch

from app.core.config import Settings

PUBLIC_EXAMPLE_JWT_SECRET = "change-this-example-secret-to-a-unique-value"  # noqa: S105 - rejection fixture


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


def test_settings_supports_the_runtime_compose_secret_directory(tmp_path: Path) -> None:
    secret_directory = tmp_path / "run" / "secrets"
    secret_directory.mkdir(parents=True)
    (secret_directory / "jwt_secret").write_text("s" * 32, encoding="utf-8")

    settings = Settings(
        _env_file=None,
        _secrets_dir=secret_directory,
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://app:app@localhost:5432/app",
    )

    assert Settings.model_config["secrets_dir"] == "/run/secrets"
    assert settings.jwt_secret.get_secret_value() == "s" * 32


def test_missing_runtime_secret_directory_is_silent_for_local_settings() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        Settings(
            _env_file=None,
            APP_ENV="test",
            DATABASE_URL="postgresql+asyncpg://app:app@localhost:5432/app",
            JWT_SECRET=SecretStr("x" * 32),
        )

    assert not [warning for warning in captured if "/run/secrets" in str(warning.message)]


@pytest.mark.parametrize(
    ("setting_name", "invalid_value"),
    [
        ("ACCESS_TOKEN_TTL_MINUTES", 0),
        ("ACCESS_TOKEN_TTL_MINUTES", -1),
        ("ACCESS_TOKEN_TTL_MINUTES", 1441),
        ("REFRESH_TOKEN_TTL_DAYS", 0),
        ("REFRESH_TOKEN_TTL_DAYS", -1),
        ("REFRESH_TOKEN_TTL_DAYS", 366),
    ],
)
def test_token_ttl_settings_reject_values_outside_policy_ranges(
    setting_name: str,
    invalid_value: int,
) -> None:
    values: dict[str, Any] = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+asyncpg://app:app@localhost:5432/app",
        "JWT_SECRET": SecretStr("x" * 32),
        setting_name: invalid_value,
    }

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    ("access_minutes", "refresh_days"),
    [
        (1, 1),
        (1440, 365),
    ],
)
def test_token_ttl_settings_accept_policy_boundaries(
    access_minutes: int,
    refresh_days: int,
) -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://app:app@localhost:5432/app",
        JWT_SECRET=SecretStr("x" * 32),
        ACCESS_TOKEN_TTL_MINUTES=access_minutes,
        REFRESH_TOKEN_TTL_DAYS=refresh_days,
    )

    assert settings.access_token_ttl_minutes == access_minutes
    assert settings.refresh_token_ttl_days == refresh_days


def test_production_rejects_public_example_secret_from_process_environment(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5432/app")
    monkeypatch.setenv("JWT_SECRET", PUBLIC_EXAMPLE_JWT_SECRET)

    with pytest.raises(ValidationError, match="public example value"):
        Settings(_env_file=None)


def test_production_rejects_public_example_secret_from_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=production",
                "DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app",
                f"JWT_SECRET={PUBLIC_EXAMPLE_JWT_SECRET}",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="public example value"):
        Settings(_env_file=env_file)


def test_production_rejects_public_example_secret_from_file_secret(tmp_path: Path) -> None:
    secret_directory = tmp_path / "run" / "secrets"
    secret_directory.mkdir(parents=True)
    (secret_directory / "jwt_secret").write_text(
        PUBLIC_EXAMPLE_JWT_SECRET,
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="public example value"):
        Settings(
            _env_file=None,
            _secrets_dir=secret_directory,
            APP_ENV="production",
            DATABASE_URL="postgresql+asyncpg://app:app@localhost:5432/app",
        )
