"""Standalone worker entrypoint.

By default the worker runs *inside the API container* (see app.main lifespan),
which is the literal §5.1 requirement. This module lets you instead run the
worker as its own process — useful to scale it out independently (set
RUN_WORKER=false on the API and run `python -m app.worker.worker`).

Liveness: after every tick the loop touches a heartbeat file so a container
healthcheck can detect a wedged worker. It also exposes its own Prometheus
metrics server (the in-process worker shares the API's /metrics instead).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from prometheus_client import start_http_server

from app.config import get_settings
from app.database import SessionLocal, engine
from app.logging_config import configure_logging
from app.worker.runner import run_loop

logger = logging.getLogger("taskpilot.worker")

HEARTBEAT_FILE = Path(os.getenv("WORKER_HEARTBEAT_FILE", "/tmp/worker.heartbeat"))


def _beat() -> None:
    try:
        HEARTBEAT_FILE.touch()
    except OSError:
        logger.warning("heartbeat_write_failed", extra={"path": str(HEARTBEAT_FILE)})


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    start_http_server(settings.worker_metrics_port)
    logger.info("worker_metrics_server_started", extra={"port": settings.worker_metrics_port})

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    try:
        await run_loop(stop, SessionLocal, settings, on_tick=_beat)
    finally:
        logger.info("worker_shutting_down")
        await engine.dispose()
        logger.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
