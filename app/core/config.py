from functools import lru_cache
from os import PathLike
from pathlib import Path
from typing import Any, Literal, Self, cast

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import PydanticBaseSettingsSource, SecretsSettingsSource


class OptionalSecretsSettingsSource(SecretsSettingsSource):
    def __call__(self) -> dict[str, Any]:
        configured = self.secrets_dir
        if configured is None:
            return {}

        directories = [configured] if isinstance(configured, (str, PathLike)) else list(configured)
        if not any(Path(directory).expanduser().exists() for directory in directories):
            return {}

        return super().__call__()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        secrets_dir="/run/secrets",
    )

    app_env: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "app_env"),
    )
    database_url: str = Field(validation_alias=AliasChoices("DATABASE_URL", "database_url"))
    jwt_secret: SecretStr = Field(validation_alias=AliasChoices("JWT_SECRET", "jwt_secret"))
    access_token_ttl_minutes: int = Field(
        default=15,
        validation_alias=AliasChoices("ACCESS_TOKEN_TTL_MINUTES", "access_token_ttl_minutes"),
    )
    refresh_token_ttl_days: int = Field(
        default=30,
        validation_alias=AliasChoices("REFRESH_TOKEN_TTL_DAYS", "refresh_token_ttl_days"),
    )
    cors_origins_raw: str = Field(
        default="",
        validation_alias=AliasChoices("CORS_ORIGINS", "cors_origins_raw"),
    )
    cors_origins: list[str] = Field(default_factory=list)
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("LOG_LEVEL", "log_level"),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        default_secret_source = cast(SecretsSettingsSource, file_secret_settings)
        optional_secret_source = OptionalSecretsSettingsSource(
            settings_cls,
            secrets_dir=default_secret_source.secrets_dir,
        )
        return init_settings, env_settings, dotenv_settings, optional_secret_source

    @model_validator(mode="before")
    @classmethod
    def normalize_environment_input(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values
        copied = dict(values)
        raw = copied.pop("CORS_ORIGINS", copied.pop("cors_origins_raw", ""))
        copied["cors_origins"] = [item.strip() for item in str(raw).split(",") if item.strip()]
        aliases = {
            "APP_ENV": "app_env",
            "DATABASE_URL": "database_url",
            "JWT_SECRET": "jwt_secret",
            "ACCESS_TOKEN_TTL_MINUTES": "access_token_ttl_minutes",
            "REFRESH_TOKEN_TTL_DAYS": "refresh_token_ttl_days",
            "LOG_LEVEL": "log_level",
        }
        for source, target in aliases.items():
            if source in copied:
                copied[target] = copied.pop(source)
        return copied

    @model_validator(mode="after")
    def validate_production_secret(self) -> Self:
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
