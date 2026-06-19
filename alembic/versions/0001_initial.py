"""initial tasks table

Revision ID: 0001
Revises:
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    task_status = postgresql.ENUM(
        "pending",
        "running",
        "succeeded",
        "failed",
        "dead",
        name="task_status",
    )
    task_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "status",
            task_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("retry_count >= 0", name="ck_tasks_retry_count_non_negative"),
        sa.CheckConstraint("length(title) > 0", name="ck_tasks_title_non_empty"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tasks_status_scheduled_at",
        "tasks",
        ["status", "scheduled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_status_scheduled_at", table_name="tasks")
    op.drop_table("tasks")
    postgresql.ENUM(name="task_status").drop(op.get_bind(), checkfirst=True)
