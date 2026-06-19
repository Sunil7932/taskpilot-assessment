"""Centralised, environment-driven configuration.

All runtime knobs live here so nothing is hardcoded and the service is fully
configurable via environment variables (12-factor).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://taskpilot:taskpilot@db:5432/taskpilot",
        alias="DATABASE_URL",
    )

    # Auth — shared secret for the internal API. No default in production:
    # the app refuses to start with the insecure placeholder (see main.py).
    api_key: str = Field(default="change-me-in-production", alias="API_KEY")

    # Worker
    worker_poll_interval_seconds: int = Field(default=60, alias="WORKER_POLL_INTERVAL_SECONDS")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    retry_backoff_base_seconds: int = Field(default=60, alias="RETRY_BACKOFF_BASE_SECONDS")
    worker_batch_size: int = Field(default=20, alias="WORKER_BATCH_SIZE")

    # App
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    max_payload_bytes: int = Field(default=65536, alias="MAX_PAYLOAD_BYTES")
    title_max_length: int = 255


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (read once per process)."""
    return Settings()
