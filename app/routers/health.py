"""Health + metrics. Unauthenticated so orchestrators/Prometheus can probe them
(restrict at the network layer in production)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.metrics import render_metrics

logger = logging.getLogger("taskpilot.health")
router = APIRouter(tags=["ops"])


@router.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Friendly landing response so the base URL isn't a bare 404."""
    return {
        "service": "TaskPilot",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus exposition for the API process."""
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Liveness: is the process up? No dependencies — never fails on DB outage,
    so an orchestrator won't kill a healthy pod just because the DB blipped.
    """
    return {"status": "ok"}


@router.get("/health")
async def readiness(
    response: Response, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    """Readiness: can we serve traffic? Probes DB connectivity."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health_check_db_failure")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}
