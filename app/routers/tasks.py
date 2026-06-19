"""/tasks endpoints. All require a valid API key."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import service
from app.auth import require_api_key
from app.database import get_session
from app.models import TaskStatus
from app.schemas import TaskCreate, TaskList, TaskRead, TaskStatusUpdate

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, session: AsyncSession = Depends(get_session)) -> TaskRead:
    task = await service.create_task(session, data)
    return TaskRead.model_validate(task)


@router.get("", response_model=TaskList)
async def list_tasks(
    session: AsyncSession = Depends(get_session),
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TaskList:
    items, total = await service.list_tasks(session, status_filter, limit, offset)
    return TaskList(
        items=[TaskRead.model_validate(t) for t in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> TaskRead:
    task = await service.get_task(session, task_id)
    return TaskRead.model_validate(task)


@router.patch("/{task_id}/status", response_model=TaskRead)
async def update_task_status(
    task_id: uuid.UUID,
    body: TaskStatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> TaskRead:
    task = await service.update_status(session, task_id, body.status)
    return TaskRead.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Response:
    await service.delete_task(session, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
