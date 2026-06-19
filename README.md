# TaskPilot 🛫

**TaskPilot runs background jobs for you.** Other services hand it a job over a
simple HTTP API ("send this receipt", "sync this data"), and TaskPilot stores it,
runs it on schedule, **retries** it if it fails, and **parks it for a human** if
it keeps failing — so no job is ever silently lost.

Built with **FastAPI + async SQLAlchemy + PostgreSQL** and a background **worker**,
all started by a single `docker compose up`. An optional **Next.js** dashboard is
included.

---

## Table of contents
1. [What problem it solves](#1-what-problem-it-solves)
2. [How it works (flow diagrams)](#2-how-it-works)
3. [Quickstart — run it in 3 steps](#3-quickstart)
4. [Try the API](#4-try-the-api)
5. [API reference](#5-api-reference)
6. [The task lifecycle (state machine)](#6-the-task-lifecycle)
7. [Configuration](#7-configuration)
8. [Running the tests](#8-running-the-tests)
9. [Key design decisions](#9-key-design-decisions)
10. [Scaling it up](#10-scaling-it-up)
11. [Production-readiness](#11-production-readiness)
12. [Project layout](#12-project-layout)
13. [AI usage disclosure](#13-ai-usage-disclosure)

---

## 1. What problem it solves

Imagine you run a SaaS platform. Lots of things need to happen *in the background*,
not while a user waits:

- 📧 send a receipt email
- 🔄 sync data to a partner's API
- 📊 regenerate a report

These jobs are **flaky** (the partner's API goes down), need to be **scheduled**
("run this in 2 hours"), and occasionally are **permanently broken** (someone
needs to look at them). TaskPilot is the small, reliable service that handles all
of that for you.

---

## 2. How it works

### The big picture — what `docker compose up` starts

```
                 ┌──────────────────────────────────────────────┐
                 │             docker compose up                 │
                 └──────────────────────────────────────────────┘
                                      │ starts
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                            ▼
   ┌─────────────┐           ┌────────────────────┐       ┌────────────────┐
   │   migrate   │  runs     │    API container   │       │   PostgreSQL   │
   │  (Alembic)  │  once,    │ ┌────────────────┐ │ reads │  "tasks" table │
   │  creates    │──exits──▶ │ │  FastAPI (API) │ │ &     │  (the source   │
   │  the schema │           │ └────────────────┘ │ writes│   of truth)    │
   └─────────────┘           │ ┌────────────────┐ │◀─────▶│                │
                             │ │  Worker loop   │ │       └────────────────┘
   ┌─────────────┐  HTTP     │ │ (every 60s)    │ │
   │ Other       │─────────▶ │ └────────────────┘ │
   │ services /  │  +X-API-Key└────────────────────┘
   │ Next.js UI  │
   └─────────────┘
```

- **migrate** runs first, creates the database tables, then exits.
- The **API container** runs *two things*: the FastAPI web API **and** the worker
  loop (in the same container, started together — exactly what the spec asks for).
- **PostgreSQL** holds all the state. The API and worker never talk directly —
  they coordinate *through the database*, which is what makes it safe and simple.

### The life of a task — from "created" to "done"

This is the core flow. Follow the numbers:

```
 ① CLIENT                    ② API                          ③ DATABASE
 ───────────                 ─────                          ──────────
 POST /tasks      ────────▶  • check API key                INSERT a row
 {title, payload}            • validate with Pydantic  ───▶ status = "pending"
                            • reject if bad/too big          scheduled_at = now
                                                                  │
                                                                  │ (time passes)
                                                                  ▼
 ④ WORKER (wakes every 60s)                              ⑤ EXECUTE THE JOB
 ──────────────────────────                             ──────────────────
 grab tasks that are due  ◀──── SELECT … FOR UPDATE      run it (here: sleep 0.5s,
 (pending & scheduled_at         SKIP LOCKED             or fail if payload has
  <= now) and lock them          (so two workers          {"force_fail": true})
 → flip them to "running"        never grab the same)            │
                                                          ┌───────┴────────┐
                                                          ▼                ▼
                                                      ✅ success        ❌ failure
                                                          │                │
                                                          ▼          retries left? (max 3)
                                                  status="succeeded"   ┌────┴─────┐
                                                                      yes         no
                                                                       ▼           ▼
                                                              status="pending"  status="dead"
                                                              try again after   (dead-letter:
                                                              backoff: 60s,      a human checks
                                                              120s, 240s…        it — never auto-
                                                                                 retried again)
```

**In words:** a service `POST`s a task → the API validates it and saves it as
`pending` → every 60 seconds the worker grabs the tasks that are due, marks them
`running`, and executes them → on success they become `succeeded`; on failure
they're retried a few times with increasing delays, and if they *still* fail they
become `dead` for a human to investigate.

The one trick that makes multiple workers safe is **`SELECT … FOR UPDATE SKIP
LOCKED`**: when a worker grabs a batch of tasks, the database locks those rows so
no other worker can grab the same ones — guaranteeing **no task runs twice**.

---

## 3. Quickstart

**You need:** [Docker](https://docs.docker.com/get-docker/) (with Docker Compose,
which ships with Docker Desktop). Nothing else — no Python, no Node.

**Step 1 — get the code**
```bash
git clone https://github.com/Sunil7932/taskpilot-assessment.git
cd taskpilot-assessment
```

**Step 2 — start everything (one command)**
```bash
docker compose up --build
```
Wait ~20s. You'll see the database start, migrations run, and the API report
`api_startup_complete`. The API is now live at **http://localhost:8000**.

**Step 3 — open the interactive docs**

Go to **http://localhost:8000/docs** in your browser — every endpoint is there,
with a try-it-out button. (Click **Authorize** and paste the API key first; the
default dev key is `change-me-in-production`.)

To stop everything: press `Ctrl+C`, then `docker compose down`.

> 🔐 **For real deployments:** copy `.env.example` to `.env` and set a strong
> `API_KEY` (`openssl rand -hex 32`). The app **refuses to start** with the
> default key when `ENVIRONMENT=production`.

---

## 4. Try the API

Every `/tasks` call needs the header `X-API-Key`. Copy-paste these:

```bash
KEY=change-me-in-production

# 1) Is it alive?  (no key needed)
curl localhost:8000/health

# 2) Create a job that will SUCCEED
curl -X POST localhost:8000/tasks -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"title":"send receipt","payload":{"order":42}}'

# 3) Create a job that will FAIL → retry → dead-letter  (use {"force_fail": true})
curl -X POST localhost:8000/tasks -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"title":"flaky sync","payload":{"force_fail":true}}'

# 4) Safe retries: send this TWICE — you get the SAME task back, not a duplicate
curl -X POST localhost:8000/tasks -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"title":"charge card","payload":{"amt":5},"idempotency_key":"order-999"}'

# 5) List tasks (filter by status + paginate)
curl "localhost:8000/tasks?status=pending&limit=20&offset=0" -H "X-API-Key: $KEY"

# 6) Watch a task change: grab its id from step 2, then poll it (wait up to 60s)
curl localhost:8000/tasks/<PASTE_ID_HERE> -H "X-API-Key: $KEY"
```

Within 60 seconds the worker picks up your tasks — the success one flips to
`succeeded`, the `force_fail` one starts climbing `retry_count` and eventually
turns `dead`.

**Optional dashboard:**
```bash
docker compose --profile frontend up --build   # then open http://localhost:3000
```

---

## 5. API reference

| Method | Path | What it does |
|--------|------|--------------|
| `POST` | `/tasks` | Create a task. Body: `title` (required), `payload` (JSON object), optional `scheduled_at`, optional `idempotency_key`. |
| `GET` | `/tasks` | List tasks. Query: `?status=`, `?limit=` (1–200), `?offset=`. |
| `GET` | `/tasks/{id}` | Fetch one task. |
| `PATCH` | `/tasks/{id}/status` | Change status (only valid transitions — see §6). |
| `DELETE` | `/tasks/{id}` | Delete a task. |
| `GET` | `/health` | Readiness — checks the DB. (no auth) |
| `GET` | `/health/live` | Liveness — is the process up. (no auth) |
| `GET` | `/metrics` | Prometheus metrics. (no auth) |

> The three `ops` endpoints (`/health`, `/health/live`, `/metrics`) are
> infrastructure, not part of the business API. `/metrics` is deliberately
> excluded from the OpenAPI schema (`include_in_schema=False`), so it won't appear
> in Swagger at `/docs` — but it works: `curl localhost:8000/metrics`.

**Errors** always look the same — never a raw stack trace:
```json
{ "error": { "code": "validation_error", "message": "title: must not be blank" } }
```

---

## 6. The task lifecycle

A task moves through exactly these states. Anything not drawn here is rejected
with **HTTP 409** (so an invalid change fails loudly instead of silently):

```
   created
      │
      ▼
  ┌─────────┐  worker claims it   ┌─────────┐   job runs OK    ┌───────────┐
  │ pending │────────────────────▶│ running │─────────────────▶│ succeeded │  ✅ done
  └─────────┘                     └─────────┘                  └───────────┘
      ▲                                │ job fails
      │ retry after backoff            ▼
      │  (60s → 120s → 240s)      ┌─────────┐  retries left?
      └───────────────────────────│ failed  │──── yes ──┘
                                  └─────────┘
                                       │ no (tried 3 times)
                                       ▼
                                  ┌─────────┐
                                  │  dead   │  ☠️  a human investigates
                                  └─────────┘     (never auto-retried)
```

`succeeded` and `dead` are final. Status changes are done **under a row lock**, so
two requests (or a request racing the worker) can't corrupt the state.

---

## 7. Configuration

Everything is configured by environment variables (12-factor). Copy
`.env.example` → `.env` and edit. The most useful ones:

| Variable | Default | Meaning |
|----------|---------|---------|
| `API_KEY` | `change-me-in-production` | Secret required in `X-API-Key`. **Change for production.** |
| `ENVIRONMENT` | `development` | Set to `production` to enforce a non-default `API_KEY`. |
| `DATABASE_URL` | local Postgres | Async SQLAlchemy connection URL. |
| `WORKER_POLL_INTERVAL_SECONDS` | `60` | How often the worker scans for due tasks. |
| `MAX_RETRIES` | `3` | Retries before a task is dead-lettered. |
| `RETRY_BACKOFF_BASE_SECONDS` | `60` | Backoff base: delay = base × 2^(attempt−1). |
| `RUN_WORKER` | `true` | Run the worker inside the API container. Set `false` to run it standalone. |
| `MAX_PAYLOAD_BYTES` | `65536` | Max size of the `payload` field. |

(See `.env.example` for the complete, commented list — pool sizes, timeouts, CORS, etc.)

---

## 8. Running the tests

Tests run against a **real PostgreSQL** (not a fake), so they'd actually catch SQL
bugs, the locking query, JSON handling, and constraint violations.

```bash
# 1) start a throwaway Postgres (or reuse the compose one)
docker run -d --name tp-test -e POSTGRES_USER=taskpilot -e POSTGRES_PASSWORD=taskpilot \
  -e POSTGRES_DB=taskpilot -p 5432:5432 postgres:16-alpine

# 2) install dev deps and run
export TEST_DATABASE_URL=postgresql+asyncpg://taskpilot:taskpilot@localhost:5432/taskpilot
pip install -r requirements-dev.txt
pytest -q
```

**CI** (GitHub Actions) runs on every push: lint (`ruff` + `black`) → types
(`mypy`) → tests on a real Postgres (+ `alembic check` for migration drift) →
Docker image build. The build fails if any step fails.

---

## 9. Key design decisions

Each choice, with the one-line reason:

| Decision | Choice | Why |
|----------|--------|-----|
| **Database** | PostgreSQL | `FOR UPDATE SKIP LOCKED` gives correct multi-worker claiming for free — SQLite can't do this. |
| **Task ID** | server-generated UUID v4 | Globally unique, and non-sequential so ids can't be guessed/enumerated (avoids IDOR). |
| **Auth** | API key in `X-API-Key` (timing-safe) | It's an internal service-to-service API; a shared secret is the simplest correct option — no OAuth/JWT needed. |
| **Worker** | plain `asyncio` loop, inside the API container | One periodic job → a bare loop is the lightest thing that works; no Celery/broker. Runs in-process per the brief; can be split out to scale. |
| **Backoff** | exponential (60s → 120s → 240s) | Gives a flaky downstream room to recover instead of hammering it. |
| **No double-execution** | `SELECT … FOR UPDATE SKIP LOCKED` | Each worker locks a disjoint set of rows, so a task is never run twice; execution happens *after* releasing the lock. |
| **Dead-letter** | a `dead` status (not a separate table) | Simpler and queryable at this scale; easy to split into a real DLQ later. |
| **Crash recovery** | a "reaper" reclaims stuck tasks | If a worker dies mid-job, the task would be stuck in `running` forever — the reaper retries it. |
| **Idempotency** | optional `idempotency_key` + unique index | A retried `POST` returns the original task instead of creating a duplicate job. |
| **Migrations** | Alembic | Real, reproducible schema; CI verifies it applies and matches the models. |

---

## 10. Scaling it up

**At ~10× traffic** (the design still holds):
- **Scale workers out**: set `RUN_WORKER=false` on the API and run N standalone
  worker processes (`python -m app.worker.worker`). `SKIP LOCKED` already makes
  concurrent claiming safe — no code change.
- Tune `WORKER_BATCH_SIZE` and DB pool sizes; the `(status, scheduled_at)` index
  already serves the claim query.
- Replace the 60s poll with Postgres **`LISTEN/NOTIFY`** so due tasks start sooner.

**At ~1000× traffic** (polling one table becomes the bottleneck):
- Move dispatch to a real broker (**Redis Streams / SQS / Kafka**); keep Postgres
  as the system of record but stop polling it on the hot path.
- **Partition** the `tasks` table and **archive** finished tasks to cold storage.
- Serve `GET /tasks` from **read replicas**; keep claims on the primary.
- Add **jitter** to backoff (avoid retry stampedes) and per-tenant rate limits.
- Extend observability: `/metrics` already ships — next add **tracing**, Grafana
  dashboards, and alerts on dead-letter/retry rates.

---

## 11. Production-readiness

**Reliability**
- 🩺 **Self-healing reaper** — tasks stuck in `running` (crashed worker) are reclaimed and retried.
- ⏱️ **Per-task timeout** — a hung job can't block the worker; it's treated as a failure.
- 🔁 **Idempotent create** — DB-enforced (partial unique index), safe under concurrent retries.
- ⚡ **Bounded concurrency** — claimed tasks run concurrently up to a cap.
- 🔌 **Resilient DB pool** — `pool_pre_ping` + recycle survive DB restarts.

**Security**
- 🚫 **Fail-closed** — refuses to boot with the default key in production.
- 🔑 Timing-safe key check · non-guessable UUIDs · validated, size-capped payloads · unknown fields rejected.
- 🛡️ **Hardened containers** — non-root, read-only filesystem, all Linux capabilities dropped, `no-new-privileges`, proper init/signal handling.
- 🙈 **No secrets in git** — `.env` ignored; everything env-driven.

**Operability**
- 📈 **Prometheus `/metrics`** — request rates/latency and task outcomes.
- 📉 **413 guard** — oversized requests rejected before they're read.
- ❤️ **Liveness vs readiness** probes (won't kill a healthy pod over a DB blip).
- 🛑 **Graceful shutdown** — finishes the in-flight tick before exiting.
- 📋 **Structured JSON logs** with a per-request id on every line.
- 🚦 **CI gates** — lint, types, tests on real Postgres, migration-drift check, image build.

---

## 12. Project layout

```
app/
  main.py            FastAPI app + starts the in-process worker (lifespan)
  config.py          all settings, from environment variables
  database.py        async DB engine + session factory
  models.py          the Task table (SQLAlchemy)
  schemas.py         request/response shapes + payload validation (Pydantic)
  state_machine.py   the allowed status transitions (one source of truth)
  service.py         create / read / update-status / delete logic
  auth.py            the X-API-Key check
  errors.py          consistent error envelope + handlers
  middleware.py      request logging + metrics + body-size guard
  metrics.py         Prometheus counters
  routers/           the HTTP endpoints (tasks, health/metrics)
  worker/            executor, claim/retry/dead-letter logic, the loop
alembic/             database migrations
tests/               API, state-machine, and worker tests (real Postgres)
frontend/            Next.js dashboard (optional bonus)
task_service_fixed.py + CODE_REVIEW.md   the §7 code-review exercise
```

---

## 13. AI usage disclosure

This solution was built with heavy AI assistance (Claude), which the brief
encourages. Every generated piece was reviewed, corrected, and verified against a
running stack and a passing test suite before it went in.

**What was AI-assisted:** essentially all of it — the FastAPI/SQLAlchemy/Alembic
scaffolding, Pydantic models, Docker/Compose/CI, the Next.js dashboard, and a
first draft of the §7 review.

**One AI suggestion I rejected (and why):** the first worker draft held the row
lock (`FOR UPDATE`) for the *entire* job execution — including the simulated
`sleep`. That serialises workers and risks lock timeouts. I replaced it with the
**claim-then-release** pattern: flip `pending → running` in a short transaction,
commit (releasing the lock), *then* execute with no lock held. A second AI draft
also read `task.payload` after its transaction closed — which fails under async
SQLAlchemy (no lazy-loading outside a transaction); the worker tests caught it and
I refactored to pass a plain dict to the executor.

**One place AI clearly sped me up:** the async **Alembic** `env.py` and the
SQLAlchemy 2.0 async engine/session wiring — fiddly boilerplate that's easy to get
subtly wrong. The first pass was nearly right; I only had to fix the duplicate
`CREATE TYPE` on the enum (`create_type=False`).

---

*See [`CODE_REVIEW.md`](CODE_REVIEW.md) for the §7 code-review exercise and
[`task_service_fixed.py`](task_service_fixed.py) for the corrected implementation.*
