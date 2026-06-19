"""add idempotency_key to tasks

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    # Partial unique index: dedupe only applies to rows that supplied a key.
    op.create_index(
        "uq_tasks_idempotency_key",
        "tasks",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tasks_idempotency_key", table_name="tasks")
    op.drop_column("tasks", "idempotency_key")
