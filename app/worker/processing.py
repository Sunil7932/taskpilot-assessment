"""Claim + process logic for the worker.

Separated from the scheduler loop so it can be unit-tested directly with a real
database session.

Concurrency & reliability model
-------------------------------
* **Claiming** uses ``SELECT ... FOR UPDATE SKIP LOCKED`` inside a transaction
  and flips ``pending -> running`` atomically. Any number of workers can run the
  same query concurrently: each gets a disjoint set of rows, so no task is
  executed twice. Execution happens *outside* the lock (we don't hold a row lock
  across slow I/O); the row is already ``running`` so no other worker picks it up.
* **Execution timeout**: each task is bounded by ``execution_timeout_seconds`` so
  a single hung task can't block a worker forever.
* **Reaper**: if a worker crashes mid-execution, its task would otherwise be
  stuck in ``running`` forever. Before each tick we reclaim tasks that have been
  ``running`` longer than ``running_task_timeout_seconds`` and retry/dead-letter
  them — this is the self-healing path that keeps the system live.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.metrics import tasks_processed_total, tasks_reclaimed_total
from app.models import Task, TaskStatus
from app.worker.executor import execute_task

logger = logging.getLogger("taskpilot.worker")


def _now() -> datetime:
    return datetime.now(UTC)


def backoff_delay_seconds(attempt: int, base: int) -> int:
    """Exponential backoff: base * 2 ** (attempt - 1). attempt is 1-based."""
    return base * (2 ** max(attempt - 1, 0))


def _apply_failure(task: Task, error: str, settings: Settings) -> None:
    """Mutate a task (inside an active transaction) to reflect a failed run.

    Either schedules a backed-off retry or dead-letters it once retries are
    exhausted. Does not commit — the caller owns the transaction.
    """
    attempt = task.retry_count + 1
    task.last_error = error[:1000]  # bounded so a noisy downstream can't bloat the row
    if attempt > settings.max_retries:
        task.status = TaskStatus.dead
        tasks_processed_total.labels(outcome="dead").inc()
        logger.warning(
            "task_dead_lettered",
            extra={"task_id": str(task.id), "retry_count": task.retry_count},
        )
    else:
        delay = backoff_delay_seconds(attempt, settings.retry_backoff_base_seconds)
        task.retry_count = attempt
        task.status = TaskStatus.pending
        task.scheduled_at = _now() + timedelta(seconds=delay)
        tasks_processed_total.labels(outcome="retried").inc()
        logger.info(
            "task_retry_scheduled",
            extra={"task_id": str(task.id), "attempt": attempt, "retry_in_seconds": delay},
        )


async def reclaim_stale_running(session: AsyncSession, settings: Settings) -> int:
    """Recover tasks stuck in `running` (e.g. their worker crashed)."""
    cutoff = _now() - timedelta(seconds=settings.running_task_timeout_seconds)
    stmt = (
        select(Task)
        .where(Task.status == TaskStatus.running, Task.updated_at < cutoff)
        .limit(settings.worker_batch_size)
        .with_for_update(skip_locked=True)
    )
    async with session.begin():
        stale = list((await session.execute(stmt)).scalars().all())
        for task in stale:
            logger.warning("task_reclaimed_stale", extra={"task_id": str(task.id)})
            tasks_reclaimed_total.inc()
            _apply_failure(task, "execution stalled (worker lost or exceeded timeout)", settings)
    return len(stale)


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
    held, bounded by an execution timeout; the result is written in a fresh
    transaction.
    """
    async with session.begin():
        task = await session.get(Task, task_id)
        if task is None or task.status != TaskStatus.running:
            return
        payload = task.payload

    try:
        await asyncio.wait_for(execute_task(payload), timeout=settings.execution_timeout_seconds)
    except TimeoutError:
        await _record_failure(
            session,
            task_id,
            f"execution exceeded {settings.execution_timeout_seconds}s timeout",
            settings,
        )
        return
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
        _apply_failure(task, error, settings)


async def run_once(session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> int:
    """One worker tick: reap stale tasks, claim due tasks, process concurrently.

    Returns the number of tasks claimed for execution (useful for tests/metrics).
    """
    async with session_factory() as session:
        await reclaim_stale_running(session, settings)

    async with session_factory() as session:
        claimed = await claim_due_tasks(session, settings.worker_batch_size)

    # Process claimed tasks concurrently, bounded so we don't open an unbounded
    # number of DB sessions. Each task uses its own session/transaction so one
    # failure can't roll back another's result.
    semaphore = asyncio.Semaphore(max(1, settings.worker_concurrency))

    async def _run(task_id) -> None:
        async with semaphore, session_factory() as session:
            await process_claimed_task(session, task_id, settings)

    if claimed:
        await asyncio.gather(*(_run(task.id) for task in claimed))

    return len(claimed)
