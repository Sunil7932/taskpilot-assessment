"""Claim + process logic for the worker.

Separated from the scheduler loop so it can be unit-tested directly with a real
database session.

Concurrency model
-----------------
Claiming uses ``SELECT ... FOR UPDATE SKIP LOCKED`` inside a transaction and
flips ``pending -> running`` atomically. Any number of workers can run the same
query concurrently: each gets a disjoint set of rows, so no task is executed
twice. Execution itself happens *outside* the lock (we don't want to hold a row
lock for the duration of slow I/O); since the row is already ``running`` no
other worker will pick it up.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Task, TaskStatus
from app.worker.executor import execute_task

logger = logging.getLogger("taskpilot.worker")


def _now() -> datetime:
    return datetime.now(UTC)


def backoff_delay_seconds(attempt: int, base: int) -> int:
    """Exponential backoff: base * 2 ** (attempt - 1). attempt is 1-based."""
    return base * (2 ** max(attempt - 1, 0))


async def claim_due_tasks(session: AsyncSession, limit: int) -> list[Task]:
    """Atomically claim up to `limit` due pending tasks, flipping them to running."""
    stmt = (
        select(Task)
        .where(Task.status == TaskStatus.pending, Task.scheduled_at <= _now())
        .order_by(Task.scheduled_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    async with session.begin():
        tasks = list((await session.execute(stmt)).scalars().all())
        for task in tasks:
            task.status = TaskStatus.running
    if tasks:
        logger.info("tasks_claimed", extra={"count": len(tasks)})
    return tasks


async def process_claimed_task(session: AsyncSession, task_id, settings: Settings) -> None:
    """Execute one already-claimed (running) task and record the outcome.

    The payload is read inside a transaction (async sessions cannot lazy-load
    attributes outside one); execution then runs with no DB transaction/lock
    held; the result is written in a fresh transaction.
    """
    async with session.begin():
        task = await session.get(Task, task_id)
        if task is None or task.status != TaskStatus.running:
            return
        payload = task.payload

    try:
        await execute_task(payload)
    except Exception as exc:  # noqa: BLE001 — convert any failure into retry/DLQ
        await _record_failure(session, task_id, str(exc), settings)
        return

    async with session.begin():
        task = await session.get(Task, task_id)
        if task is None:
            return
        task.status = TaskStatus.succeeded
        task.last_error = None
    logger.info("task_succeeded", extra={"task_id": str(task_id)})


async def _record_failure(session: AsyncSession, task_id, error: str, settings: Settings) -> None:
    async with session.begin():
        task = await session.get(Task, task_id)
        if task is None:
            return
        attempt = task.retry_count + 1
        # Keep error messages bounded so a noisy downstream can't bloat the row.
        task.last_error = error[:1000]
        if attempt > settings.max_retries:
            task.status = TaskStatus.dead
            logger.warning(
                "task_dead_lettered",
                extra={"task_id": str(task_id), "retry_count": task.retry_count},
            )
        else:
            delay = backoff_delay_seconds(attempt, settings.retry_backoff_base_seconds)
            task.retry_count = attempt
            task.status = TaskStatus.pending
            task.scheduled_at = _now() + timedelta(seconds=delay)
            logger.info(
                "task_retry_scheduled",
                extra={
                    "task_id": str(task_id),
                    "attempt": attempt,
                    "retry_in_seconds": delay,
                },
            )


async def run_once(session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> int:
    """One worker tick: claim due tasks and process each in isolation.

    Returns the number of tasks processed (useful for tests/metrics).
    """
    async with session_factory() as session:
        claimed = await claim_due_tasks(session, settings.worker_batch_size)

    for task in claimed:
        # Each task gets its own session/transaction so one failure can't roll
        # back another's result.
        async with session_factory() as session:
            await process_claimed_task(session, task.id, settings)

    return len(claimed)
