"""task_service_fixed.py — corrected version of the §7 review file.

Self-contained and runnable. Fixes every issue listed in CODE_REVIEW.md:

  * parameterised queries (no SQL injection)
  * Pydantic validation of untrusted input (shape + bounds)
  * genuine async I/O via aiosqlite (no blocking calls under `async def`)
  * one connection opened at startup and closed at shutdown (no per-request leak)
  * a single JOIN instead of N+1, selecting only needed columns (no data leak)
  * API-key auth
  * consistent error envelope; no bare `except`
  * the over-engineered factory/repository indirection removed

Run: `pip install fastapi uvicorn aiosqlite pydantic` then
`uvicorn task_service_fixed:app`. Auth header: `X-API-Key: dev-key`.
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import aiosqlite
from fastapi import Depends, FastAPI, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field, field_validator

DB_PATH = os.getenv("DB_PATH", "tasks.db")
API_KEY = os.getenv("API_KEY", "dev-key")
MAX_PAYLOAD_BYTES = 64 * 1024


# --------------------------------------------------------------------------- #
# App + connection lifecycle (one connection, opened/closed once).
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row  # fixes 2.2: index rows by column name
    await db.execute("PRAGMA journal_mode=WAL;")  # safer concurrent reads
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            payload TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        );
        """
    )
    await db.commit()
    app.state.db = db
    try:
        yield
    finally:
        await db.close()


app = FastAPI(lifespan=lifespan)


async def get_db() -> aiosqlite.Connection:
    return app.state.db


# --------------------------------------------------------------------------- #
# Auth (fixes 1.3).
# --------------------------------------------------------------------------- #
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(provided: str | None = Security(_api_key_header)) -> None:
    if not provided or not secrets.compare_digest(provided, API_KEY):
        raise _ApiError(401, "unauthorized", "Missing or invalid API key.")


# --------------------------------------------------------------------------- #
# Validation models (fixes 1.4, 2.3, 2.5).
# --------------------------------------------------------------------------- #
class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # reject unknown fields

    title: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)
    user_id: int | None = None

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v

    @field_validator("payload")
    @classmethod
    def _bounded(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v).encode()) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload too large")
        return v


class TaskRead(BaseModel):
    id: str
    title: str
    payload: dict[str, Any]
    status: str
    created_at: str
    user: dict[str, Any] | None


# --------------------------------------------------------------------------- #
# Error envelope (fixes 2.4).
# --------------------------------------------------------------------------- #
class _ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code, self.code, self.message = status_code, code, message
        super().__init__(message)


@app.exception_handler(_ApiError)
async def _handle_api_error(_, exc: _ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(Exception)
async def _handle_unexpected(_, __: Exception) -> JSONResponse:
    # Log server-side (omitted here); never leak internals to the client.
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "An internal error occurred."}},
    )


# --------------------------------------------------------------------------- #
# Endpoints — parameterised queries only (fixes 1.1, 1.2, 3.1, 3.2, 3.3, 4.1, 5.x).
# --------------------------------------------------------------------------- #
@app.post("/tasks", status_code=201, dependencies=[Depends(require_api_key)])
async def create_task(body: TaskCreate, db: aiosqlite.Connection = Depends(get_db)) -> TaskRead:
    task_id = str(uuid.uuid4())
    created_at = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO tasks (id, title, payload, user_id, status, created_at) "
        "VALUES (?, ?, ?, ?, 'pending', ?)",
        (task_id, body.title, json.dumps(body.payload), body.user_id, created_at),
    )
    await db.commit()
    return TaskRead(
        id=task_id,
        title=body.title,
        payload=body.payload,
        status="pending",
        created_at=created_at,
        user=None,
    )


@app.get("/tasks", dependencies=[Depends(require_api_key)])
async def get_tasks(db: aiosqlite.Connection = Depends(get_db)) -> list[TaskRead]:
    # Single JOIN, only the columns we need (no N+1, no SELECT *).
    async with db.execute(
        """
        SELECT t.id, t.title, t.payload, t.status, t.created_at,
               u.id AS user_id, u.name AS user_name
        FROM tasks t
        LEFT JOIN users u ON u.id = t.user_id
        ORDER BY t.created_at DESC
        """
    ) as cursor:
        rows = await cursor.fetchall()

    return [
        TaskRead(
            id=r["id"],
            title=r["title"],
            payload=json.loads(r["payload"]),
            status=r["status"],
            created_at=r["created_at"],
            user={"id": r["user_id"], "name": r["user_name"]} if r["user_id"] else None,
        )
        for r in rows
    ]
