"""Structured JSON logging.

One config used by both the API and the worker so logs are uniform and
machine-parseable in production (ingestible by Loki/CloudWatch/etc.).
"""

from __future__ import annotations

import logging

from pythonjsonlogger import json as jsonlogger


def configure_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(
        jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # uvicorn duplicates access logs through its own handlers; our middleware
    # already emits a structured per-request log, so silence the duplicate.
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
