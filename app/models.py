"""SQLAlchemy ORM models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    dead = "dead"


class Task(Base):
    __tablename__ = "tasks"

    # UUID v4: globally unique, generated server-side without DB coordination,
    # and non-sequential so task ids can't be enumerated (mitigates IDOR).
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # JSONB: untrusted, schema-validated at the API boundary (see schemas.py).
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Optional client-supplied dedupe key: a retried create with the same key
    # returns the original task instead of creating a duplicate (see service.py).
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", native_enum=True),
        nullable=False,
        default=TaskStatus.pending,
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("retry_count >= 0", name="ck_tasks_retry_count_non_negative"),
        CheckConstraint("length(title) > 0", name="ck_tasks_title_non_empty"),
        # Hot path for the worker claim query: due, pending tasks oldest-first.
        Index(
            "ix_tasks_status_scheduled_at",
            "status",
            "scheduled_at",
        ),
        # Enforce dedupe at the DB level (the source of truth under concurrency).
        Index(
            "uq_tasks_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )
