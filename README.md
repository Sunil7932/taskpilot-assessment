# TaskPilot

A small, self-contained service that accepts background jobs over an internal
HTTP API, runs them on a schedule, retries flaky failures with backoff, and
dead-letters the permanently broken ones for a human to inspect.

Built with **FastAPI + async SQLAlchemy + PostgreSQL**, a **polling worker**, and
a one-command **Docker Compose** stack. An optional **Next.js** dashboard is
included as a bonus.

---

## How to run

Prerequisites: Docker + Docker Compose.

```bash
# from the repo root — builds and starts db + migrations + api + worker
docker compose up --build
```

That single command:
1. starts **PostgreSQL** and waits until it is healthy,
2. runs a one-shot **migrate** service (`alembic upgrade head`) to create the schema,
3. starts the **API** on http://localhost:8000 (health-checked), and
4. starts the **worker**, which scans for due tasks every 60s.

The API requires an `X-API-Key` header. The default dev key is
`change-me-in-production` (override via a `.env` file — see `.env.example`).

> Note: the stack works out of the box with safe local defaults. Copy
> `.env.example` to `.env` and set a strong `API_KEY` before any real deployment.

### Try it

```bash
KEY=change-me-in-production

# health (no auth)
curl localhost:8000/health

# create a task that will succeed
curl -X POST localhost:8000/tasks -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"title":"send receipt","payload":{"order":42}}'

# create a task that will fail -> retried with backoff -> dead-lettered
curl -X POST localhost:8000/tasks -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"title":"flaky","payload":{"force_fail":true}}'

# idempotent create — sending this twice returns the SAME task, no duplicate
curl -X POST localhost:8000/tasks -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"title":"charge card","payload":{"amt":5},"idempotency_key":"order-999"}'

# list (filter + paginate)
curl "localhost:8000/tasks?status=pending&limit=20&offset=0" -H "X-API-Key: $KEY"

# liveness (no DB) vs readiness (probes DB) — both unauthenticated
curl localhost:8000/health/live
curl localhost:8000/health

# Prometheus metrics — API process, and the worker on its own port
curl localhost:8000/metrics
curl localhost:9100/metrics
```

Interactive API docs: http://localhost:8000/docs

### Optional dashboard

```bash
docker compose --profile frontend up --build   # then open http://localhost:3000
```

### Tests

Tests run against a **real Postgres** (not a stub), so the SKIP-LOCKED claim
query, JSONB, enums, and constraints are genuinely exercised.

```bash
# point at any throwaway Postgres
export TEST_DATABASE_URL=postgresql+asyncpg://taskpilot:taskpilot@localhost:5432/taskpilot
pip install -r requirements-dev.txt
pytest -q
```

CI runs lint (ruff + black + mypy) → tests (against a Postgres service, incl.
`alembic check` for migration drift) → image build.

---

## Architecture

```
                         X-API-Key
   other services ───────────────────▶ ┌─────────────────┐
   (HTTP clients)                       │   FastAPI API   │
                                        │  /tasks /health │
   ┌──────────────┐   poll every 60s    │ Pydantic + auth │
   │  Next.js UI  │──▶ (server proxy) ──▶│  + logging mw   │
   └──────────────┘                     └────────┬────────┘
                                                  │ async SQLAlchemy
                                                  ▼
                                        ┌─────────────────┐
                                        │   PostgreSQL    │
                                        │   tasks table   │
                                        └────────▲────────┘
                                                  │ SELECT ... FOR UPDATE
                                                  │ SKIP LOCKED  (claim)
                                        ┌────────┴────────┐
                                        │     Worker      │  execute → succeed
                                        │  asyncio loop   │  or fail → retry
                                        │  (own process)  │  (backoff) → dead
                                        └─────────────────┘
```

The **API** is a thin, async FastAPI app: Pydantic validates every request, a
middleware logs each request (method, path, status, latency, request id), and a
single exception layer returns a consistent error envelope. The **worker** is a
separate process running the same image; every 60s it atomically claims due
`pending` tasks, executes them outside any lock, and records the outcome
(succeeded / retry-with-backoff / dead). State lives entirely in Postgres, so the
API and worker share no in-memory state and can be scaled independently.

### Project layout

```
app/
  main.py            FastAPI app factory + lifespan
  config.py          env-driven settings (pydantic-settings)
  database.py        async engine + session factory
  models.py          Task ORM model
  schemas.py         Pydantic request/response models (payload validation)
  state_machine.py   allowed status transitions (single source of truth)
  service.py         task persistence + transition logic
  auth.py            API-key dependency
  errors.py          error envelope + exception handlers
  middleware.py      request-logging middleware
  routers/           tasks + health endpoints
  worker/            executor, claim/process logic, asyncio loop entrypoint
alembic/             async migration env + initial schema
tests/               API, state-machine, and worker tests (real Postgres)
frontend/            Next.js dashboard (optional bonus)
task_service_fixed.py + CODE_REVIEW.md   §7 review exercise
```

---

## Key decisions (each with a one-line why)

| Decision | Choice | Why |
|----------|--------|-----|
| **Database** | PostgreSQL | `SELECT ... FOR UPDATE SKIP LOCKED` gives correct multi-worker task claiming out of the box — SQLite can't, and we need real concurrency. |
| **ID** | UUID v4 (server-generated) | Globally unique without DB coordination and non-sequential, so task ids can't be enumerated (mitigates IDOR). |
| **Auth** | API key in `X-API-Key` (timing-safe compare) | This is an internal service-to-service API; a shared secret is the simplest correct control — no need for OAuth/JWT. |
| **Worker** | Plain `asyncio` polling loop, separate process | Exactly one periodic job; a bare loop is the lightest thing that works — zero extra deps, no broker, trivial graceful shutdown. |
| **Backoff** | Exponential (`base · 2^attempt`, base 60s) | Flaky downstreams recover better when not hammered; exponential spacing (60s → 120s → 240s) backs off fast without extra infra. |
| **Concurrency** | `FOR UPDATE SKIP LOCKED` claim, status flipped to `running` in one txn | Multiple workers run the same claim query and each gets a disjoint row set, so no task is ever executed twice; execution happens outside the lock so slow I/O doesn't hold rows. |
| **Dead-letter** | `status = 'dead'` on the same table | A separate DLQ table adds migration/ops overhead with no benefit at this scale; a terminal status is queryable and simple. Easy to split out later. |
| **Crash recovery** | Reaper reclaims stale `running` tasks | A worker can die mid-task; without this the task is stuck forever. The reaper makes the system self-heal. |
| **Idempotency** | Optional `idempotency_key` + partial unique index | Other services retry create calls; the key dedupes so a retry returns the original task instead of duplicating work. |
| **Migrations** | Alembic (async env) | Production-realistic, reproducible schema; CI verifies migrations apply *and* checks model drift (`alembic check`). |

### Status state machine

```
pending ──claim──▶ running ──ok──▶ succeeded (terminal)
   ▲                  │
   └── retry (backoff)┤── fail, retries left ──▶ failed ──▶ pending
                      └── fail, retries exhausted ─────────▶ dead (terminal)
```

Invalid transitions via `PATCH /tasks/{id}/status` return **409** (not a silent
success). Transitions are applied under a row lock so two concurrent updates (or
a PATCH racing the worker) can't clobber each other.

---

## What I'd change at scale

**~10× traffic** (the polling design still holds):
- Run **multiple worker replicas** — `SKIP LOCKED` already makes this safe; no code change, just `docker compose up --scale worker=N`.
- Tune `WORKER_BATCH_SIZE` and pool sizes; the `(status, scheduled_at)` index already supports the claim query.
- Shorten the poll interval or add Postgres **`LISTEN/NOTIFY`** so newly-due tasks start sooner than the next 60s tick.
- Add **idempotency keys** on create so retried client requests don't duplicate jobs.

**~1000× traffic** (polling a single table becomes the bottleneck):
- Move dispatch off the primary DB to a purpose-built broker (**Redis Streams / SQS / Kafka**); keep Postgres as the system of record but stop polling it for the hot path.
- **Partition** the `tasks` table (by created_at/status) and **archive** terminal tasks (`succeeded`/`dead`) to cold storage so the active set stays small.
- Serve `GET /tasks` from **read replicas**; keep claims on the primary.
- Add **jitter** to backoff to avoid retry stampedes, and per-tenant **rate limiting**/quotas.
- Extend **observability**: Prometheus `/metrics` already ship (request + task outcome counters); next add distributed **tracing**, Grafana dashboards, and alerting on DLQ/retry-rate growth and queue depth.
- Split the dead-letter path into its own store/queue with replay tooling for operators.

---

## Production-readiness notes

**Reliability / self-healing**
- **Stale-task reaper**: if a worker dies mid-execution, its task would be stuck in `running` forever. Each tick first reclaims tasks `running` past `RUNNING_TASK_TIMEOUT_SECONDS` and retries/dead-letters them. *(see `reclaim_stale_running`)*
- **Per-task execution timeout** (`EXECUTION_TIMEOUT_SECONDS`): a hung task can't block the worker — it's treated as a failure and retried.
- **Idempotent create**: clients may send `idempotency_key`; a retried create returns the original task instead of duplicating. Enforced by a DB **partial unique index** (the real guard under concurrency), with the insert race handled gracefully.
- **Bounded concurrent processing** (`WORKER_CONCURRENCY`): claimed tasks execute concurrently with a semaphore cap, so throughput scales without unbounded DB sessions.
- **Connection-pool tuning**: `pool_pre_ping` + `pool_recycle` + configurable sizes survive DB restarts and stale connections.

**Security**
- **Fail-closed config**: with `ENVIRONMENT=production`, the app **refuses to start** if `API_KEY` is the insecure default.
- Timing-safe API-key comparison; **non-sequential UUIDs** (no IDOR enumeration); untrusted `payload` validated for shape + size; unknown fields rejected.
- **Container hardening**: non-root user, `read_only` root filesystem (+ tmpfs `/tmp`), `cap_drop: ALL`, `no-new-privileges`, `init: true` for correct signal handling/zombie reaping.
- **No secrets in the repo**: `.env` git-ignored; everything env-configurable (`.env.example` documents every variable).

**Operability**
- **Prometheus metrics**: the API serves `/metrics` (request count/latency by route, tasks created); the worker — a separate process — exposes its own metrics on `:9100` (tasks succeeded/retried/dead-lettered/reclaimed). Endpoint labels use the route template so cardinality stays bounded.
- **Request-body guard**: requests over `MAX_REQUEST_BYTES` are rejected with `413` before the body is read (bounds memory).
- **Liveness** (`/health/live`, no deps) vs **readiness** (`/health`, probes DB) — so an orchestrator won't kill a healthy pod over a transient DB blip. The worker exposes a **heartbeat-file healthcheck**.
- **Graceful shutdown**: worker traps SIGTERM/SIGINT, finishes the in-flight tick, disposes the engine (`stop_grace_period: 30s`); uvicorn drains on signal.
- **Structured JSON logs** with a request-id **contextvar** so every log line in a request (not just the access log) is correlated; generic client errors, never leaking stack traces/SQL.
- **Resource limits** (cpu/memory) per service; multi-stage lean image with version-pinned bases.
- **CI gates**: ruff + black + **mypy**, tests on a real Postgres, **`alembic check`** (model/migration drift), and image build.

---

## Scope I intentionally cut

- **No DLQ table** — a `dead` status is enough at this size (documented above).
- **No update/edit endpoint** beyond status — not in the spec; tasks are created then driven by the worker.
- The optional frontend is deliberately minimal (polling, no client cache library) — the brief rewards state-management restraint.

---

## AI usage disclosure

This solution was built with heavy AI assistance (Claude), which is encouraged by
the brief. How it was used:

**AI-assisted parts:** essentially all of it — scaffolding the FastAPI/SQLAlchemy/
Alembic boilerplate, the Pydantic models, the Docker/Compose/CI files, the
Next.js dashboard, and a first draft of the §7 review. Every piece was reviewed,
corrected, and verified against a running stack and a passing test suite before
inclusion.

**One AI suggestion I rejected (and why):** the first worker draft held the
row lock (`FOR UPDATE`) for the *entire* duration of task execution — i.e. across
the simulated `await asyncio.sleep(0.5)`. That serialises workers and risks lock
timeouts under load. I rejected it for the **claim-then-release** pattern: flip
`pending → running` in a short transaction, commit (releasing the lock), then
execute with no lock held. A *second* AI draft also passed the ORM `Task` object
into the executor and read `task.payload` after the transaction closed — that
fails under async SQLAlchemy (it can't lazy-load attributes outside a
transaction). The worker tests caught it, and I refactored to read the payload
inside the transaction and pass a plain dict to the executor.

**One place AI clearly helped me move faster:** the async **Alembic** `env.py`
and the SQLAlchemy 2.0 async session/engine wiring — fiddly boilerplate that's
easy to get subtly wrong. AI produced a correct first pass that I only had to
tweak (e.g. fixing the duplicate `CREATE TYPE` on the enum with
`create_type=False`).
