"""Structured JSON logging.

One config used by both the API and the worker so logs are uniform and
machine-parseable in production (ingestible by Loki/CloudWatch/etc.). A
context-local request id is injected into every record emitted while handling a
request, so all logs for one request can be correlated — not just the access log.
"""

from __future__ import annotations

import contextvars
import logging

from pythonjsonlogger import json as jsonlogger

# Set by the request-logging middleware; read by the logging filter below.
request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class RequestIdFilter(logging.Filter):
    """Attach the current request id (if any) to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            rid = request_id_ctx.get()
            if rid is not None:
                record.request_id = rid
        return True


def configure_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(
        jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        )
    )
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # uvicorn duplicates access logs through its own handlers; our middleware
    # already emits a structured per-request log, so silence the duplicate.
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
