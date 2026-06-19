"""Prometheus metrics.

Definitions are shared by both processes; each process exposes only what it
increments (the API serves /metrics; the worker runs its own metrics HTTP
server). Unused counters simply report 0 in the process that doesn't touch them.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# --- HTTP (API process) ---------------------------------------------------
http_requests_total = Counter(
    "taskpilot_http_requests_total",
    "Total HTTP requests handled by the API.",
    ["method", "endpoint", "status"],
)
http_request_duration_seconds = Histogram(
    "taskpilot_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "endpoint"],
)

# --- Tasks ----------------------------------------------------------------
tasks_created_total = Counter(
    "taskpilot_tasks_created_total",
    "Tasks created via the API (excludes idempotent no-ops).",
)
tasks_processed_total = Counter(
    "taskpilot_tasks_processed_total",
    "Tasks processed by the worker, labelled by outcome.",
    ["outcome"],  # succeeded | retried | dead
)
tasks_reclaimed_total = Counter(
    "taskpilot_tasks_reclaimed_total",
    "Stale 'running' tasks reclaimed by the reaper.",
)


def render_metrics() -> tuple[bytes, str]:
    """Serialise the default registry for a /metrics response."""
    return generate_latest(), CONTENT_TYPE_LATEST
