"""Task persistence + business logic.

A thin functional service over SQLAlchemy — no repository/factory indirection,
because at this size it would be ceremony without payoff (see CODE_REVIEW.md).
All writes go through parameterised queries; transitions go through the state
machine.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models import Task, TaskStatus
from app.schemas import TaskCreate
from app.state_machine import can_transition


async def _find_by_idempotency_key(session: AsyncSession, key: str) -> Task | None:
    result = await session.execute(select(Task).where(Task.idempotency_key == key))
    return result.scalar_one_or_none()


async def create_task(session: AsyncSession, data: TaskCreate) -> Task:
    # Idempotency: if this key was already used, return the original task instead
    # of creating a duplicate. The DB unique index is the real guard; this is the
    # fast path that also handles the concurrent-insert race below.
    if data.idempotency_key is not None:
        existing = await _find_by_idempotency_key(session, data.idempotency_key)
        if existing is not None:
            return existing

    task = Task(
        title=data.title,
        payload=data.payload,
        idempotency_key=data.idempotency_key,
        # created_at / status / retry_count default server-side, never from client.
    )
    if data.scheduled_at is not None:
        task.scheduled_at = data.scheduled_at
    session.add(task)
    try:
        await session.commit()
    except IntegrityError:
        # Two concurrent creates raced on the same idempotency_key; the loser
        # rolls back and returns the winner's row.
        await session.rollback()
        if data.idempotency_key is not None:
            existing = await _find_by_idempotency_key(session, data.idempotency_key)
            if existing is not None:
                return existing
        raise
    await session.refresh(task)
    return task


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise ApiError(404, "not_found", "Task not found.")
    return task


async def list_tasks(
    session: AsyncSession,
    status: TaskStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[Task], int]:
    base = select(Task)
    count_q = select(func.count()).select_from(Task)
    if status is not None:
        base = base.where(Task.status == status)
        count_q = count_q.where(Task.status == status)

    total = (await session.execute(count_q)).scalar_one()
    rows = (
        (await session.execute(base.order_by(Task.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return list(rows), total


async def delete_task(session: AsyncSession, task_id: uuid.UUID) -> None:
    task = await get_task(session, task_id)
    await session.delete(task)
    await session.commit()


async def update_status(session: AsyncSession, task_id: uuid.UUID, target: TaskStatus) -> Task:
    """Apply a status transition under a row lock to prevent lost updates.

    Two concurrent PATCHes (or a PATCH racing the worker) serialise on the row;
    the second sees the post-commit state and is validated against it.
    """
    async with session.begin():
        result = await session.execute(select(Task).where(Task.id == task_id).with_for_update())
        task = result.scalar_one_or_none()
        if task is None:
            raise ApiError(404, "not_found", "Task not found.")

        if task.status == target:
            return task  # idempotent no-op

        if not can_transition(task.status, target):
            raise ApiError(
                409,
                "invalid_transition",
                f"Cannot transition task from '{task.status.value}' to '{target.value}'.",
            )
        task.status = target
    await session.refresh(task)
    return task
