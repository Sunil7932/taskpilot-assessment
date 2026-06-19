"""Async SQLAlchemy engine + session factory.

A single async engine per process; sessions are created per-request (API) or
per-tick (worker) and always closed. No global shared connection.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

# pool_pre_ping avoids handing out dead connections after a DB restart.
engine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped session."""
    async with SessionLocal() as session:
        yield session
