"""Task status state machine.

Single source of truth for allowed transitions, used by both the API
(PATCH /tasks/{id}/status) and the worker. Any transition not listed here is
rejected (409 at the API layer).

    pending  ──claim──▶ running ──ok──▶ succeeded
       ▲                   │
       │                   └──fail──▶ failed ──retry (backoff)──▶ pending
       │                                  │
       └──────────────────────────────────┘
                                          └──retries exhausted──▶ dead

`succeeded` and `dead` are terminal.
"""

from __future__ import annotations

from app.models import TaskStatus

ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.pending: {TaskStatus.running, TaskStatus.dead},
    TaskStatus.running: {TaskStatus.succeeded, TaskStatus.failed},
    TaskStatus.failed: {TaskStatus.pending, TaskStatus.dead},
    TaskStatus.succeeded: set(),  # terminal
    TaskStatus.dead: set(),  # terminal
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())
