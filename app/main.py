"""FastAPI application factory + wiring."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import INSECURE_DEFAULT_API_KEY, get_settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware import RequestLoggingMiddleware
from app.routers import health, tasks

logger = logging.getLogger("taskpilot.app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    # In production, an insecure-default key would already have failed settings
    # validation; in dev we just warn loudly.
    if settings.api_key == INSECURE_DEFAULT_API_KEY:
        logger.warning(
            "insecure_api_key_in_use",
            extra={"hint": "Set a strong API_KEY before deploying to production."},
        )
    logger.info("api_startup_complete", extra={"environment": settings.environment})
    yield
    logger.info("api_shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TaskPilot",
        description="Internal background-job service: accept, schedule, retry, dead-letter tasks.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS is off by default (server-to-server API); enable explicitly per env.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(tasks.router)
    return app


app = create_app()
