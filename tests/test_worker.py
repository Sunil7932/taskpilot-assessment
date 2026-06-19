"""Worker tests: success, retry, dead-letter, scheduling, and concurrency."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.config import get_settings
from app.models import Task, TaskStatus
from app.worker.processing import backoff_delay_seconds, reclaim_stale_running, run_once


@pytest.fixture
def settings():
    return get_settings()


async def _insert(session_factory, **kwargs) -> uuid.UUID:
    defaults = {
        "title": "t",
        "payload": {},
        "scheduled_at": datetime.now(UTC) - timedelta(seconds=1),
        "status": TaskStatus.pending,
        "retry_count": 0,
    }
    defaults.update(kwargs)
    async with session_factory() as session:
        async with session.begin():
            task = Task(**defaults)
            session.add(task)
        return task.id


async def _get(session_factory, task_id) -> Task:
    async with session_factory() as session:
        return await session.get(Task, task_id)


async def test_successful_task_marked_succeeded(session_factory, settings):
    task_id = await _insert(session_factory)
    processed = await run_once(session_factory, settings)
    assert processed == 1
    task = await _get(session_factory, task_id)
    assert task.status == TaskStatus.succeeded
    assert task.last_error is None


async def test_force_fail_schedules_retry_with_backoff(session_factory, settings):
    task_id = await _insert(session_factory, payload={"force_fail": True})
    await run_once(session_factory, settings)
    task = await _get(session_factory, task_id)
    assert task.status == TaskStatus.pending  # requeued
    assert task.retry_count == 1
    assert task.last_error is not None
    assert task.scheduled_at > datetime.now(UTC)  # backed off into future


async def test_dead_letter_after_retries_exhausted(session_factory, settings):
    # retry_count already at the max → the next failure exhausts retries.
    task_id = await _insert(
        session_factory, payload={"force_fail": True}, retry_count=settings.max_retries
    )
    await run_once(session_factory, settings)
    task = await _get(session_factory, task_id)
    assert task.status == TaskStatus.dead


async def test_future_task_is_not_claimed(session_factory, settings):
    task_id = await _insert(session_factory, scheduled_at=datetime.now(UTC) + timedelta(hours=1))
    processed = await run_once(session_factory, settings)
    assert processed == 0
    task = await _get(session_factory, task_id)
    assert task.status == TaskStatus.pending


async def test_concurrent_workers_do_not_double_process(session_factory, settings):
    ids = [await _insert(session_factory) for _ in range(6)]
    # Two workers tick at the same time; SKIP LOCKED must partition the rows.
    results = await asyncio.gather(
        run_once(session_factory, settings),
        run_once(session_factory, settings),
    )
    assert sum(results) == len(ids)  # each task claimed exactly once
    for task_id in ids:
        task = await _get(session_factory, task_id)
        assert task.status == TaskStatus.succeeded


def test_backoff_is_exponential():
    assert backoff_delay_seconds(1, 60) == 60
    assert backoff_delay_seconds(2, 60) == 120
    assert backoff_delay_seconds(3, 60) == 240


async def test_execution_timeout_is_treated_as_failure(session_factory, settings):
    # Force the per-task timeout below the simulated work (0.5s) so it trips.
    tight = settings.model_copy(update={"execution_timeout_seconds": 0})
    task_id = await _insert(session_factory)  # normal task, would otherwise succeed
    await run_once(session_factory, tight)
    task = await _get(session_factory, task_id)
    assert task.status == TaskStatus.pending  # requeued for retry
    assert task.retry_count == 1
    assert "timeout" in (task.last_error or "")


async def test_reaper_reclaims_stale_running_task(session_factory, settings):
    # A task left in `running` long ago (e.g. its worker crashed mid-flight).
    stale_since = datetime.now(UTC) - timedelta(seconds=settings.running_task_timeout_seconds + 60)
    task_id = await _insert(session_factory, status=TaskStatus.running, updated_at=stale_since)
    async with session_factory() as session:
        reclaimed = await reclaim_stale_running(session, settings)
    assert reclaimed == 1
    task = await _get(session_factory, task_id)
    assert task.status == TaskStatus.pending  # back in the queue
    assert task.retry_count == 1
    assert "stalled" in (task.last_error or "")


async def test_reaper_ignores_fresh_running_task(session_factory, settings):
    # A task that just started running must NOT be reaped.
    task_id = await _insert(
        session_factory, status=TaskStatus.running, updated_at=datetime.now(UTC)
    )
    async with session_factory() as session:
        reclaimed = await reclaim_stale_running(session, settings)
    assert reclaimed == 0
    task = await _get(session_factory, task_id)
    assert task.status == TaskStatus.running
