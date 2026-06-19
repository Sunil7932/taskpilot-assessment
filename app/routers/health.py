"""Health check. Unauthenticated so orchestrators can probe it."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session

logger = logging.getLogger("taskpilot.health")
router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    response: Response, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    """Liveness + DB readiness in one probe."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health_check_db_failure")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}
