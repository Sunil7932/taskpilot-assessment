"""FastAPI application factory + wiring."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import INSECURE_DEFAULT_API_KEY, get_settings
from app.database import SessionLocal
from app.errors import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware import RequestLoggingMiddleware
from app.routers import health, tasks
from app.worker.runner import run_loop

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

    # §5.1: the worker runs inside the API container, started by the same
    # `docker compose up`. It's a background task on the app event loop and is
    # shut down gracefully (the in-flight tick finishes) when the app stops.
    worker_stop: asyncio.Event | None = None
    worker_task: asyncio.Task[None] | None = None
    if settings.run_worker:
        worker_stop = asyncio.Event()
        worker_task = asyncio.create_task(run_loop(worker_stop, SessionLocal, settings))
        logger.info("in_process_worker_started")

    logger.info("api_startup_complete", extra={"environment": settings.environment})
    try:
        yield
    finally:
        if worker_stop is not None and worker_task is not None:
            worker_stop.set()
            await worker_task  # let the current tick drain before exiting
            logger.info("in_process_worker_stopped")
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
