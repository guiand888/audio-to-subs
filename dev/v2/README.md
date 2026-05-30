# audio-to-subs v2 — Architecture & Implementation Docs

This folder contains the design and implementation plan for **v2** of `audio-to-subs`: a self-hosted web application built on top of the existing transcription pipeline.

It is meant to be read by a developer (or AI agent) about to implement the v2 architecture from scratch. Documents are intentionally concrete: filenames, dependencies pinned to versions, SQL statements, and acceptance criteria are spelled out.

## How v2 differs from v1

| | v1 (today) | v2 |
|---|---|---|
| Surface | CLI only (`audio-to-subs -i video.mp4 -o out.srt`) | Web app + CLI (CLI unchanged) |
| Source of jobs | User-supplied paths | Bazarr "wanted" list, or manual paths |
| Concurrency | None (synchronous) | Job queue, separate worker container(s) |
| State | Filesystem only | SQLite (jobs, history, logs, settings, Bazarr cache) |
| Observability | stdout progress | Live web UI with SSE, history, logs page |

## Reading order

1. [`ARCHITECTURE.md`](ARCHITECTURE.md) — top-level overview, repo layout, service topology
2. [`MIGRATION.md`](MIGRATION.md) — how to refactor `src/` → `audio_to_subs/` without breaking the CLI (**M0**)
3. [`DATABASE.md`](DATABASE.md) — schema, indexes, Alembic strategy
4. [`QUEUE.md`](QUEUE.md) — worker lifecycle, claim protocol, cancellation, reaper
5. [`API.md`](API.md) — every FastAPI route
6. [`FRONTEND.md`](FRONTEND.md) — Vite/React/shadcn stack, pages, SSE consumption
7. [`BAZARR_INTEGRATION.md`](BAZARR_INTEGRATION.md) — client, poller, path mapping
8. [`AUTH.md`](AUTH.md) — single-admin model, argon2 + signed cookies, bootstrap
9. [`PIPELINE_CHANGES.md`](PIPELINE_CHANGES.md) — additive changes to `core/` (cancel token, cost, structured progress)
10. [`DEPLOYMENT.md`](DEPLOYMENT.md) — docker-compose, secrets, volumes
11. [`TESTING.md`](TESTING.md) — test layout, tricky cases
12. [`MILESTONES.md`](MILESTONES.md) — M0–M6 with acceptance criteria

A required pre-implementation spike is documented in [`MISTRAL_USAGE_PROBE.md`](MISTRAL_USAGE_PROBE.md) — it must complete before milestone M2.

## Fixed decisions

These were chosen during planning and should be treated as constraints, not options to revisit during implementation. If implementation surfaces a strong reason to change one, raise it before deviating.

| Topic | Choice |
|---|---|
| Worker model | Separate worker container(s); API container does not run jobs |
| Bazarr configuration | Single instance, configured at server level via env vars |
| Authentication | Single admin user (multi-user-ready schema), signed-cookie sessions |
| Frontend deploy | Separate Nginx container; backend serves no static assets |
| Media access | Worker mounts the same media volume as Bazarr; configurable path-mapping |
| Queue | SQLite for durability + Redis for live pub/sub. **No** Celery/RQ/Arq |
| Cost tracking | Parse usage from Mistral API response; duration × rate fallback |
| CLI compatibility | CLI keeps working unchanged — pipeline becomes a shared library |

## Status

- **As of writing**: all v1 work merged on `main` (120+ tests passing, ≥80% coverage). No v2 code has been written yet.
- **Next action**: complete the [Mistral usage probe](MISTRAL_USAGE_PROBE.md), then start [milestone M0](MILESTONES.md).
