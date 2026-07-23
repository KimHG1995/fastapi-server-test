from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str
    jwt_secret: SecretStr
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    cors_origins_raw: str = ""
    cors_origins: list[str] = []
    log_level: str = "INFO"

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
