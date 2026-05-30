# v2 — Architecture Overview

## Purpose

Promote `audio-to-subs` from a one-shot CLI to a self-hosted web application that polls Bazarr, queues transcription jobs, runs them in dedicated workers, and surfaces history, logs, and settings through a shadcn/ui frontend — without breaking the existing CLI.

## Service topology

```
┌──────────────┐       HTTP /api      ┌──────────────┐
│  frontend    │ ─────────────────▶   │   backend    │
│  (Nginx +    │                       │  (FastAPI +  │
│   Vite build)│ ◀── SSE ─────────    │   uvicorn)   │
└──────────────┘                       └──────┬───────┘
                                              │
                                  ┌───────────┼────────────┐
                                  │           │            │
                            ┌─────▼─────┐  ┌──▼─────┐  ┌──▼──────────┐
                            │  redis    │  │ sqlite │  │  Bazarr     │
                            │ (pub/sub) │  │ (data) │  │  (external) │
                            └─────▲─────┘  └──▲─────┘  └─────────────┘
                                  │           │
                                  │           │
                            ┌─────┴───────────┴────┐
                            │  worker (1..N)       │
                            │  python -m           │
                            │   audio_to_subs.     │
                            │   worker             │
                            └──────────────────────┘
                                       │
                                       ▼
                                ┌────────────┐
                                │ media vol  │  ← same mount Bazarr sees
                                └────────────┘
```

Four containers in `docker-compose.yml`: **backend**, **worker** (≥1 replica), **frontend**, **redis**. SQLite lives on a named volume mounted by backend + worker. Media lives on an external volume shared with Bazarr.

## Repo layout (post-M0)

```
audio-to-subs/
  pyproject.toml
  requirements.txt              # runtime, includes web stack
  requirements-dev.txt
  docker-compose.yml
  Dockerfile                    # backend + worker share image
  frontend/
    Dockerfile                  # Nginx + static build
    nginx.conf
    package.json
    vite.config.ts
    tsconfig.json
    index.html
    src/
      main.tsx
      router.tsx
      lib/{api.ts,sse.ts,auth.ts,query.ts}
      components/ui/...         # shadcn primitives
      components/{Layout,JobCard,LiveBadge,...}.tsx
      pages/{Login,Wanted,Queue,History,Logs,Settings}.tsx
      hooks/{useJobsStream.ts,useAuth.ts}
      styles/globals.css
  audio_to_subs/
    __init__.py
    __main__.py                 # delegates to cli.main
    cli.py                      # unchanged CLI surface, imports core
    core/                       # all existing pipeline modules live here
      __init__.py
      pipeline.py
      audio_extractor.py
      audio_splitter.py
      transcription_client.py
      subtitle_generator.py
      config_parser.py
      logging_config.py
      cancel.py                 # new: CancelToken
      cost.py                   # new: parse Mistral usage / fallback
    db/
      __init__.py
      base.py                   # SQLAlchemy Base, engine factory, WAL pragmas
      models.py                 # User, Job, JobLog, Setting, BazarrCache
      session.py                # async + sync session factories
      migrations/               # Alembic
        env.py
        versions/
    auth/
      __init__.py
      passwords.py              # argon2 hash/verify
      sessions.py               # itsdangerous signed cookies
      deps.py                   # FastAPI dependencies (current_user)
      bootstrap.py              # first-boot admin creation
    bazarr/
      __init__.py
      client.py                 # async httpx client
      pathmap.py                # bazarr_prefix -> local_prefix
      poller.py                 # background polling task
      schemas.py                # pydantic models for Bazarr payloads
    queue_/
      __init__.py
      claim.py                  # SQLite claim transaction
      events.py                 # Redis channel names, publishers
      reaper.py                 # stale 'running' job reaper
    api/
      __init__.py
      app.py                    # FastAPI factory, CORS, lifespan
      settings.py               # pydantic-settings
      deps.py                   # request-scoped DB session, auth
      sse.py                    # sse-starlette wrapper
      routes/
        auth.py
        jobs.py
        wanted.py
        history.py
        logs.py
        settings.py
        bazarr.py
        stream.py
    worker/
      __init__.py
      __main__.py               # python -m audio_to_subs.worker
      runner.py                 # claim loop, progress bridge, cancel
      progress.py               # progress callback → DB + Redis
    admin/
      __init__.py
      __main__.py               # set-password, create-user, db-init
  tests/
    test_*.py                   # mirrors source tree
    fixtures/
  dev/
    v2/                         # this folder
```

### Why a real `audio_to_subs/` package instead of keeping `src/`

- Imports like `from src.foo import …` leak build-tree naming into runtime; renaming makes the worker/api code cleaner and supports `python -m audio_to_subs.worker`.
- The console script entry point becomes natural: `audio-to-subs = "audio_to_subs.cli:main"`.
- The rename is mechanical (one `git mv` + one `sed`) and is covered by M0's acceptance gate: the existing test suite must pass unchanged. See [`MIGRATION.md`](MIGRATION.md).

## Data flow — happy path for a Bazarr-sourced job

1. **Poll**: backend's Bazarr poller hits `/api/movies/wanted` + `/api/episodes/wanted` every N minutes (default 1 h). Results upserted into `bazarr_cache`.
2. **List**: user opens `/wanted` in the UI. Frontend calls `GET /api/wanted?…`. Backend reads from `bazarr_cache` only — never blocks on a live Bazarr call.
3. **Enqueue**: user clicks "Transcribe" on a row. Frontend posts `POST /api/jobs {source: "bazarr_episode", source_ref: "<sonarrEpisodeId>", language_code, output_format}`. Backend resolves `media_path` via `bazarr/pathmap.py`, inserts a `jobs` row with `status=queued`, publishes `jobs:new` on Redis.
4. **Claim**: a worker subscribed to `jobs:new` runs the claim SQL ([`QUEUE.md`](QUEUE.md)). The `UPDATE … RETURNING` atomically promotes one row to `running` and returns its fields.
5. **Run**: worker calls `core.pipeline.Pipeline(...).process_video(...)` with a `CancelToken` and a structured progress callback. The callback writes `progress_percent` + `progress_message` to the job row (debounced) and publishes every event on `jobs:progress:<id>` and `jobs:global`.
6. **Stream**: backend has one asyncio task subscribed to `jobs:global` that fans events out to all connected SSE clients on `/api/jobs/stream`. The frontend's global `EventSource` updates a Zustand store keyed by job id; the Wanted and Queue pages re-render selectively.
7. **Finish**: worker writes `mistral_usage_json`, `estimated_cost_usd`, `audio_duration_seconds`, sets `status=done`, appends a final `job_logs` entry, publishes `jobs:done:<id>`, and best-effort calls Bazarr to rescan the affected item (logged either way).

Cancellation, crash recovery, and reaper behavior are covered in [`QUEUE.md`](QUEUE.md).

## Technology choices

### Backend

- **FastAPI** with async routes. Pydantic v2 throughout (mistralai 2.4.5 already pulls Pydantic v2 — no conflict).
- **SQLAlchemy 2.x** with the async engine (`aiosqlite`) for the API and the sync engine for the worker. **Alembic** from day 1.
- **redis-py 5.x** (both async and sync facets) for pub/sub only — no streams, no persistence. Redis is not the source of truth.
- **sse-starlette** for Server-Sent Events.
- **httpx** for the Bazarr client.
- **argon2-cffi** for password hashing; **itsdangerous** for signed-cookie sessions.

### Frontend

- **Vite + React 18 + TypeScript + Tailwind + shadcn/ui** + TanStack Query + TanStack Router.
- Black & white palette via shadcn's neutral preset. Light / Dark / Auto themes (Auto follows `prefers-color-scheme`).
- Single global `EventSource('/api/jobs/stream')` mounted in the root layout drives all live updates.

### Infra

- **Nginx** (`nginx:1.27-alpine`) serves the static frontend and proxies `/api`. `proxy_buffering off` is required for SSE.
- **SQLite** with WAL mode is fine for 1 API + 1–3 workers. Document Postgres as the upgrade path (only `DATABASE_URL` change + `alembic upgrade head` needed).

## Cross-cutting design decisions

| Decision | Rationale |
|---|---|
| Progress is a column on `jobs`, not an events table | Live progress is high-frequency; the audit trail lives in `job_logs` (append-only, milestone messages only) |
| No `sessions` table | itsdangerous signed cookies are stateless; revocation can be bolted on later via a 10-line migration |
| Redis pub/sub, not streams | SQLite is the source of truth; Redis only carries ephemeral events |
| Bazarr poller writes to `bazarr_cache`, UI reads cache only | UI stays snappy; Bazarr isn't hit on every page load |
| `rescan_movie` / `rescan_episode` are stubs | The exact Bazarr endpoint is unknown (see `dev/reference/BAZARR_API_RESEARCH.md`); centralised so the wiring is a one-file change later |
| `mistralai==2.4.5` stays sync; the worker is sync | No need to rewrite the transcription client. The API never calls Mistral directly. |

## What v2 does NOT include

To keep scope tight:

- No multi-tenant accounts (schema is multi-user-ready, but only one admin is created).
- No webhook receiver from Bazarr (polling only — Bazarr doesn't push today).
- No automatic subtitle quality scoring or post-processing.
- No translation, only transcription.
- No Postgres support in the initial release (DSN is configurable, but only SQLite is tested).
- No PyPI release (matches v1 stance in `dev/v1/` docs).
