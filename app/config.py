"""Centralised, environment-driven configuration.

All runtime knobs live here so nothing is hardcoded and the service is fully
configurable via environment variables (12-factor).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_API_KEY = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Deployment environment. When set to "production" the app refuses to start
    # with the insecure default API key (fail closed, not open).
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://taskpilot:taskpilot@db:5432/taskpilot",
        alias="DATABASE_URL",
    )
    # Connection-pool tuning. Defaults are sane for a small service; raise for
    # higher concurrency. pool_recycle guards against stale server-side conns.
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="DB_MAX_OVERFLOW")
    db_pool_timeout_seconds: int = Field(default=30, alias="DB_POOL_TIMEOUT_SECONDS")
    db_pool_recycle_seconds: int = Field(default=1800, alias="DB_POOL_RECYCLE_SECONDS")

    # Auth — shared secret for the internal API.
    api_key: str = Field(default=INSECURE_DEFAULT_API_KEY, alias="API_KEY")

    # CORS — comma-separated allowed origins. Empty (default) disables CORS,
    # which is correct for a server-to-server internal API.
    cors_allow_origins: str = Field(default="", alias="CORS_ALLOW_ORIGINS")

    # Worker
    worker_poll_interval_seconds: int = Field(default=60, alias="WORKER_POLL_INTERVAL_SECONDS")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    retry_backoff_base_seconds: int = Field(default=60, alias="RETRY_BACKOFF_BASE_SECONDS")
    worker_batch_size: int = Field(default=20, alias="WORKER_BATCH_SIZE")
    # How many claimed tasks the worker executes concurrently per tick.
    worker_concurrency: int = Field(default=5, alias="WORKER_CONCURRENCY")
    # Hard cap on a single task's execution; exceeding it counts as a failure.
    execution_timeout_seconds: int = Field(default=30, alias="EXECUTION_TIMEOUT_SECONDS")
    # A task stuck in `running` longer than this (e.g. worker crashed mid-flight)
    # is reclaimed by the reaper and retried/dead-lettered.
    running_task_timeout_seconds: int = Field(default=300, alias="RUNNING_TASK_TIMEOUT_SECONDS")

    # Port the worker process exposes its Prometheus metrics on.
    worker_metrics_port: int = Field(default=9100, alias="WORKER_METRICS_PORT")

    # App
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    max_payload_bytes: int = Field(default=65536, alias="MAX_PAYLOAD_BYTES")
    # Hard ceiling on the whole request body (Content-Length); rejected with 413
    # before the body is read, to bound memory use. Generous vs max_payload_bytes.
    max_request_bytes: int = Field(default=1_048_576, alias="MAX_REQUEST_BYTES")
    title_max_length: int = 255

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _reject_insecure_production_config(self) -> Settings:
        if self.is_production and self.api_key == INSECURE_DEFAULT_API_KEY:
            raise ValueError(
                "API_KEY is set to the insecure default while ENVIRONMENT=production. "
                "Set a strong API_KEY (e.g. `openssl rand -hex 32`) before deploying."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (read once per process)."""
    return Settings()
