"""Pydantic request/response models.

The `payload` field is untrusted input from other services, so it is validated
for shape (must be a JSON object) and size (serialised bytes bounded).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import get_settings
from app.models import TaskStatus

_settings = get_settings()

TitleStr = Annotated[str, Field(min_length=1, max_length=_settings.title_max_length)]


def _validate_payload(value: dict[str, Any]) -> dict[str, Any]:
    # Must be a JSON object (Pydantic already enforces dict typing here).
    # Bound the serialised size to prevent oversized-payload abuse / DoS.
    encoded = json.dumps(value, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) > _settings.max_payload_bytes:
        raise ValueError(
            f"payload exceeds maximum size of {_settings.max_payload_bytes} bytes"
        )
    return value


class TaskCreate(BaseModel):
    # Reject unknown fields rather than silently dropping them.
    model_config = ConfigDict(extra="forbid")

    title: TitleStr
    payload: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v

    @field_validator("payload")
    @classmethod
    def _check_payload(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_payload(v)

    @field_validator("scheduled_at")
    @classmethod
    def _normalise_scheduled_at(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        # Normalise naive datetimes to UTC; store everything tz-aware.
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class TaskStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TaskStatus


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    payload: dict[str, Any]
    scheduled_at: datetime
    status: TaskStatus
    retry_count: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class TaskList(BaseModel):
    items: list[TaskRead]
    total: int
    limit: int
    offset: int


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
