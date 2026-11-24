from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://loss_app:loss_app_dev_password@localhost:5433/loss_intelligence"
)
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://loss_app:loss_app_dev_password@localhost:5433/loss_intelligence_test"
)
DEFAULT_TEST_ADMIN_DATABASE_URL = (
    "postgresql+psycopg://loss_app:loss_app_dev_password@localhost:5433/postgres"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["local", "test", "ci"] = "local"
    log_level: str = "INFO"
    db_echo: bool = False
    database_url: str = DEFAULT_DATABASE_URL
    test_database_url: str = DEFAULT_TEST_DATABASE_URL
    test_admin_database_url: str = DEFAULT_TEST_ADMIN_DATABASE_URL

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return normalized

    @field_validator("database_url", "test_database_url", "test_admin_database_url")
    @classmethod
    def _validate_postgres_url(cls, value: str) -> str:
        url = make_url(value)
        if url.drivername != "postgresql+psycopg":
            raise ValueError("database URLs must use the postgresql+psycopg driver")
        if not url.database:
            raise ValueError("database URLs must include a database name")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
