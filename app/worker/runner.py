"""The worker polling loop, shared by the in-process worker (started in the API
lifespan, per §5.1) and the standalone entrypoint (`app.worker.worker`).

A plain ``asyncio`` loop — the lightest thing that meets the brief: one periodic
job, zero extra deps, no broker, and graceful shutdown is trivial (we cancel the
inter-tick sleep on stop but always let the in-flight tick finish first).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.worker.processing import run_once

logger = logging.getLogger("taskpilot.worker")


async def run_loop(
    stop: asyncio.Event,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    on_tick: Callable[[], None] | None = None,
) -> None:
    interval = settings.worker_poll_interval_seconds
    logger.info("worker_started", extra={"poll_interval_seconds": interval})
    if on_tick:
        on_tick()

    while not stop.is_set():
        start = time.monotonic()
        try:
            await run_once(session_factory, settings)
        except Exception:  # noqa: BLE001 — never let one tick kill the loop
            logger.exception("worker_tick_failed")
        if on_tick:
            on_tick()

        # Sleep the remainder of the interval, but wake immediately on shutdown.
        elapsed = time.monotonic() - start
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.0, interval - elapsed))
        except TimeoutError:
            pass

    logger.info("worker_loop_exited")
