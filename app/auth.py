"""API-key authentication.

Chosen over rate-limiting per the brief: this is an *internal* service-to-service
API, so a shared secret in a header is the simplest correct way to keep
unauthenticated callers out. Compared with `==`, `secrets.compare_digest`
avoids leaking the key via timing.
"""

from __future__ import annotations

import secrets

from fastapi import Security
from fastapi.security import APIKeyHeader

from app.config import get_settings
from app.errors import ApiError

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(provided: str | None = Security(_api_key_header)) -> None:
    expected = get_settings().api_key
    if not provided or not secrets.compare_digest(provided, expected):
        raise ApiError(
            status_code=401,
            code="unauthorized",
            message="Missing or invalid API key.",
        )
