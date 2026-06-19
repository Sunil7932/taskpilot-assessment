"""Worker entrypoint: a plain asyncio polling loop.

Why a plain loop (not APScheduler/Celery)? We have exactly one periodic job
(scan every N seconds). A bare ``asyncio`` loop is the lightest thing that
satisfies the brief: zero extra dependencies, no broker, and graceful shutdown
is trivial — we cancel the inter-tick sleep on SIGTERM but always let the
in-flight tick finish first.

Liveness: after every tick the loop touches a heartbeat file. A container
healthcheck can assert the file is recent to detect a wedged/dead worker.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from pathlib import Path

from app.config import get_settings
from app.database import SessionLocal, engine
from app.logging_config import configure_logging
from app.worker.processing import run_once

logger = logging.getLogger("taskpilot.worker")

HEARTBEAT_FILE = Path(os.getenv("WORKER_HEARTBEAT_FILE", "/tmp/worker.heartbeat"))


def _beat() -> None:
    try:
        HEARTBEAT_FILE.touch()
    except OSError:
        logger.warning("heartbeat_write_failed", extra={"path": str(HEARTBEAT_FILE)})


async def _loop(stop: asyncio.Event) -> None:
    settings = get_settings()
    interval = settings.worker_poll_interval_seconds
    logger.info("worker_started", extra={"poll_interval_seconds": interval})
    _beat()

    while not stop.is_set():
        start = time.monotonic()
        try:
            await run_once(SessionLocal, settings)
        except Exception:  # noqa: BLE001 — never let one tick kill the loop
            logger.exception("worker_tick_failed")
        _beat()

        # Sleep the remainder of the interval, but wake immediately on shutdown.
        elapsed = time.monotonic() - start
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.0, interval - elapsed))
        except TimeoutError:
            pass


async def main() -> None:
    configure_logging(get_settings().log_level)
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    try:
        await _loop(stop)
    finally:
        logger.info("worker_shutting_down")
        await engine.dispose()
        logger.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
