"""FastAPI application factory + wiring."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware import RequestLoggingMiddleware
from app.routers import health, tasks

logger = logging.getLogger("taskpilot.app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.api_key == "change-me-in-production":
        logger.warning(
            "insecure_api_key_in_use",
            extra={"hint": "Set a strong API_KEY before deploying to production."},
        )
    logger.info("api_startup_complete")
    yield
    logger.info("api_shutdown_complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="TaskPilot",
        description="Internal background-job service: accept, schedule, retry, dead-letter tasks.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(tasks.router)
    return app


app = create_app()
