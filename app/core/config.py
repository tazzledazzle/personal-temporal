"""
Application settings via pydantic-settings.

All configuration is read from environment variables (or .env file).
The API key is stored as SecretStr to prevent accidental logging of the raw value.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_key: SecretStr
    database_url: str = "sqlite+aiosqlite:////app/data/workflows.db"
    log_json: bool = True
    app_version: str = "0.1.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings instance (one per process)."""
    return Settings()
