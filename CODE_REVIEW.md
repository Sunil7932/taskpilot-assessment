# Code Review — `task_service.py` (§7)

The provided file is ~50 lines but contains a critical security hole, code that
**cannot run at all**, an N+1 query, resource leaks, blocking I/O behind `async`,
and architecture that adds indirection while hiding the bugs. Below: every issue
I found, grouped by category, each with impact and the concrete fix. The
corrected, runnable version is in [`task_service_fixed.py`](task_service_fixed.py).

> TL;DR: **do not ship this.** It would either crash on the first `POST /tasks`
> (AttributeError) or, where it does run, allow trivial SQL injection and leak
> entire user records.

---

## 1. Security

### 1.1 SQL injection — `CWE-89` (Critical)
```python
query = f"INSERT INTO tasks (title, payload) VALUES ('{title}', '{payload}')"
...
f"SELECT * FROM users WHERE id = {t['user_id']}"
```
**Impact:** `title`/`payload` come straight from the request body. A title of
`x'); DROP TABLE tasks;--` (or worse, a sub-select to exfiltrate the `users`
table) executes arbitrary SQL. This is the single most severe issue.
**Fix:** never build SQL with f-strings. Use parameterised queries (`?`
placeholders / bound parameters) everywhere so values are sent out-of-band:
```python
await db.execute("INSERT INTO tasks (id, title, payload, ...) VALUES (?, ?, ?, ...)",
                 (task_id, title, payload_json, ...))
```

### 1.2 Mass data exposure via `SELECT *` on `users` — `CWE-200` (High)
`get_tasks` joins each task to its owner with `SELECT * FROM users` and returns
the **whole user row** to the caller — potentially password hashes, emails,
tokens, PII. `SELECT *` also silently leaks any column added later.
**Fix:** select only the columns the endpoint needs (`id`, `name`) and return a
typed response model. Never `SELECT *` across a trust boundary.

### 1.3 No authentication / rate limiting — `CWE-306` (High)
Every endpoint is open. The brief requires at least one of auth or rate limiting.
**Fix:** require an API key (see fixed version; matches the main service’s choice).

### 1.4 Unvalidated, unbounded untrusted input — `CWE-20` (High)
`data["title"]` / `data["payload"]` are used with no type, length, shape, or size
checks. A 50 MB payload or wrong types are accepted.
**Fix:** Pydantic request models — non-empty bounded `title`, `payload` must be a
JSON object with a size cap, unknown fields rejected.

---

## 2. Correctness (this code does not work)

### 2.1 `AttributeError` on every create — the method references a field that doesn’t exist
```python
async def create_task(self, title, payload):
    repo = self.factory.create_repository()   # created, never used
    cursor = self.conn.cursor()               # TaskService has no `self.conn`!
```
**Impact:** `TaskService` has `self.factory`, not `self.conn`. The first
`POST /tasks` raises `AttributeError` and returns a generic 500. The endpoint is
**100% broken**, and the bare `except` (see 2.4) hides why.
**Fix:** go through one real connection/session; drop the dead `repo` line.

### 2.2 Row access by column name without `Row` factory — `TypeError`
```python
for t in tasks:
    ... t['user_id'] ...
```
**Impact:** `sqlite3` returns plain tuples by default; `t['user_id']` raises
`TypeError: tuple indices must be integers`. Indexing rows by name requires
`conn.row_factory = sqlite3.Row`.
**Fix:** set a row factory (or map columns explicitly) and reference fields safely.

### 2.3 `payload` serialised as a Python `repr`, not JSON
Interpolating a dict into `'{payload}'` stores `{'k': 'v'}` (single quotes) — not
valid JSON, and not round-trippable.
**Fix:** `json.dumps(payload)` into a `TEXT`/JSON column; parse on read.

### 2.4 Bare `except:` swallows everything — `CWE-396`
```python
except:
    raise HTTPException(status_code=500, detail="Error")
```
**Impact:** catches *everything* including `KeyboardInterrupt`/`SystemExit`,
turns a missing-field `KeyError` (should be 422) into an opaque 500, and destroys
the traceback so the bug above is invisible in logs.
**Fix:** validate input with Pydantic (auto-422), let unexpected errors hit a
single structured exception handler that logs server-side and returns a generic
envelope.

### 2.5 `POST` returns no resource and the wrong status
Returns `{"status": "created"}` with HTTP 200 — no `id`, not 201, not the row.
**Fix:** return the created task (with server-generated `id`/timestamps) and 201.

---

## 3. Performance / Resources

### 3.1 N+1 query — `CWE-1073`
`get_tasks` runs `1 + N` queries (one per task to fetch its user).
**Impact:** 500 tasks → 501 queries; latency scales with row count.
**Fix:** a single `LEFT JOIN users` (see fixed version).

### 3.2 Connection leak — a new connection per request, never closed — `CWE-404`
`TaskService()` is constructed in every handler, and its
`AbstractRepositoryFactory.__init__` calls `sqlite3.connect(...)` each time. None
are ever closed. File handles/connections leak until exhaustion.
**Fix:** one engine/connection pool created at startup (lifespan), sessions
acquired per request and always closed.

### 3.3 Blocking I/O inside `async def` — fake async
Handlers are `async` but call synchronous `sqlite3` — blocking the event loop and
serialising all requests. The brief explicitly forbids this.
**Fix:** use a genuinely async driver (`aiosqlite` / async SQLAlchemy) so awaits
yield the loop.

---

## 4. Concurrency

### 4.1 One shared `sqlite3` connection across the process — `CWE-662`
A single module-level connection shared by all requests. `sqlite3` connections
are not safe to use concurrently (and trip `check_same_thread`); concurrent
writes corrupt state or raise.
**Fix:** a pool / per-request session, or for SQLite a serialised access path.
(The main TaskPilot service uses Postgres with `FOR UPDATE SKIP LOCKED` for this
reason.)

---

## 5. Design / Maintainability

### 5.1 Over-engineered factory/repository indirection
`AbstractRepositoryFactory` → `TaskRepository` is exactly the "patterns that don’t
earn their keep" the brief warns against. It adds two layers, yet the service
bypasses the repository anyway (`self.conn.execute(...)`), so the abstraction is
both useless and actively hiding bug 2.1.
**Fix:** delete it. A thin module of `async def` functions over one connection is
simpler and clearer at this size.

### 5.2 No separation of model/validation; `SELECT *`; no migrations/schema
No request/response schemas, no defined table schema, brittle `SELECT *`.
**Fix:** Pydantic models + an explicit, documented schema.

---

## Summary table

| # | Category | Issue | Severity |
|---|----------|-------|----------|
| 1.1 | Security | SQL injection (f-string queries) | Critical |
| 1.2 | Security | `SELECT *` leaks full user rows | High |
| 1.3 | Security | No auth / rate limiting | High |
| 1.4 | Security | Unvalidated, unbounded input | High |
| 2.1 | Correctness | `self.conn` undefined → crashes on create | Critical |
| 2.2 | Correctness | Row indexed by name without `Row` factory | High |
| 2.3 | Correctness | Payload stored as Python repr, not JSON | Medium |
| 2.4 | Correctness | Bare `except` hides errors, wrong codes | High |
| 2.5 | Correctness | POST returns no resource, wrong status | Low |
| 3.1 | Performance | N+1 query for users | Medium |
| 3.2 | Performance | Connection leak (new conn/request) | High |
| 3.3 | Performance | Blocking I/O under `async` | High |
| 4.1 | Concurrency | Shared unsafe `sqlite3` connection | High |
| 5.1 | Design | Useless factory/repository indirection | Medium |
| 5.2 | Design | No schemas / `SELECT *` / no schema setup | Medium |

See [`task_service_fixed.py`](task_service_fixed.py) for the corrected implementation.
