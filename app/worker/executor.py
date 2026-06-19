"""Simulated task execution.

Per the brief: a payload containing {"force_fail": true} fails; everything else
succeeds after a short simulated delay. This is the only place "real work"
would later be dispatched (e.g. send receipt, call partner API).
"""

from __future__ import annotations

import asyncio

from app.models import Task


class TaskExecutionError(Exception):
    """Raised when simulated execution fails (triggers retry/dead-letter)."""


async def execute_task(task: Task) -> None:
    if isinstance(task.payload, dict) and task.payload.get("force_fail") is True:
        raise TaskExecutionError("payload requested forced failure")
    # Simulate I/O-bound work without blocking the event loop.
    await asyncio.sleep(0.5)
