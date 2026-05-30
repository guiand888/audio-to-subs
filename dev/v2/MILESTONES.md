# v2 — Milestones

Six milestones, each independently shippable and reviewable. The order encodes hard dependencies — do not parallelise across milestones unless explicitly noted.

Every milestone ends with the same quality bar:

- `pytest` green
- `black`, `ruff`, `mypy --strict` clean
- New code ≥ 80% coverage
- Conventional commit prefixes (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`)
- All commits include `Signed-off-by:` per the repo's commit message template

## M0 — Repo restructure: `src/` → `audio_to_subs/`

**Goal**: relocate the v1 pipeline into a real package with a `core/` subpackage. No behaviour changes.

Tasks:
- [`MIGRATION.md`](MIGRATION.md) mechanical rename + import rewrites.
- Update `pyproject.toml` entry point and package config.
- Update Dockerfile/Compose paths and `python -m` entrypoints.

Acceptance:
- `pytest` passes unchanged (no test logic changed; only import paths).
- `audio-to-subs --version` works.
- `audio-to-subs -i dev/test_video.mp4 -o /tmp/out.srt` produces the same SRT as before M0.
- Container builds and runs the CLI end-to-end.

Out of scope: any new code under `db/`, `api/`, `worker/`, etc. Add the empty `core/__init__.py`; everything else lands in later milestones.

## M0.5 — Mistral usage probe (one-off spike, blocks M2)

Run [`MISTRAL_USAGE_PROBE.md`](MISTRAL_USAGE_PROBE.md). Document the exact response shape of `mistralai==2.4.5`'s transcription endpoint in that file. Decide whether `core/cost.py` reads real usage or falls back to duration × rate.

Acceptance: `MISTRAL_USAGE_PROBE.md` updated with concrete findings; `core/cost.py` field accesses are pinned to actual field names.

This is a documentation milestone — no code commit other than the optional probe script (which can be deleted after).

## M1 — DB foundation + auth + FastAPI scaffold

**Goal**: a backend container that boots, runs migrations, bootstraps the admin user, and serves `/api/auth/{login,logout,me}` + `/api/healthz`.

Tasks:
- `audio_to_subs/db/`: `base.py` (engine + WAL pragmas), `models.py` (all v2 tables), `session.py` (async + sync session factories), `migrations/` (Alembic with initial revision).
- `audio_to_subs/auth/`: `passwords.py`, `sessions.py`, `deps.py`, `bootstrap.py`.
- `audio_to_subs/admin/__main__.py`: `set-password`, `db-init`, `whoami` subcommands.
- `audio_to_subs/api/`: `app.py` (FastAPI factory + lifespan that runs `alembic upgrade head` and `bootstrap_admin`), `settings.py` (`pydantic-settings`), `deps.py`, `routes/auth.py`, `routes/__init__.py`, `routes/healthz.py`.
- `Dockerfile`: switch CMD to uvicorn.
- `docker-compose.yml`: backend + redis services (no worker, no frontend yet).
- Tests: `test_db_models.py`, `test_db_migrations.py`, `test_auth_*`, `test_api_auth.py`, `test_api_healthz.py`.

Acceptance:
- `docker compose up backend redis` brings the API up; `/api/healthz` returns 200.
- `POST /api/auth/login` round-trip works against a freshly bootstrapped admin (from env).
- Alembic migration applied; WAL pragma observed on connections.

## M2 — Worker, queue, Pipeline cancellation, cost

**Goal**: end-to-end manual job. Operator can `POST /api/jobs {source:"manual", media_path:"..."}` and watch progress via SSE; cancellation and crash recovery work.

Tasks:
- `audio_to_subs/core/cancel.py` (`CancelToken`, `Cancelled`).
- `audio_to_subs/core/cost.py` (`extract_usage`, `compute_cost`) — uses the probe findings.
- `audio_to_subs/core/pipeline.py`: add `cancel_token` + `structured_progress_callback` + `PipelineResult` (additive; CLI unchanged).
- `audio_to_subs/core/audio_extractor.py`, `audio_to_subs/core/audio_splitter.py`: accept `cancel_token` kwarg; terminate FFmpeg on cancel.
- `audio_to_subs/queue_/`: `claim.py`, `events.py`, `reaper.py`.
- `audio_to_subs/worker/`: `__main__.py`, `runner.py`, `progress.py`.
- `audio_to_subs/api/routes/jobs.py`: create, list, detail, cancel.
- `audio_to_subs/api/routes/stream.py`: `/api/jobs/stream` and `/api/jobs/{id}/stream` (sse-starlette).
- `audio_to_subs/api/routes/logs.py`: `/api/jobs/{id}/logs`.
- `docker-compose.yml`: add `worker` service.
- Tests: `test_core_cancel.py`, `test_core_cost.py`, `test_core_pipeline_structured.py`, `test_queue_claim.py`, `test_queue_reaper.py`, `test_worker_runner.py`, `test_api_jobs.py`, `test_api_stream.py`.

Acceptance:
- Submit a manual job; SSE shows progress events; row reaches `done` with non-null `audio_duration_seconds`, `estimated_cost_usd`, and either a populated `mistral_usage_json` or NULL (depending on probe result).
- `POST /api/jobs/{id}/cancel` mid-run terminates FFmpeg within 1 s; row reaches `cancelled`.
- Kill the worker mid-run; within ≤120 s the row is reaped and another worker (or the restarted worker) re-picks it up.

## M3 — Bazarr client + poller + `/api/wanted`

**Goal**: the UI-less plumbing for the Wanted page. From the operator's perspective, hit `/api/wanted` and get filtered, normalised items resolved to local paths.

Tasks:
- `audio_to_subs/bazarr/`: `schemas.py`, `client.py`, `pathmap.py`, `poller.py`.
- `audio_to_subs/api/app.py`: start the poller in the lifespan.
- `audio_to_subs/api/routes/wanted.py`: read from `bazarr_cache`, join `jobs` for `active_job_id`, apply filters.
- Extend `POST /api/jobs` to resolve `source=bazarr_movie|bazarr_episode` via `bazarr_cache` + `pathmap`.
- `audio_to_subs/api/routes/settings.py`: GET/PATCH settings (so the poller interval and pathmap are editable at runtime).
- Tests: `test_bazarr_client.py`, `test_bazarr_pathmap.py`, `test_bazarr_poller.py`, `test_api_wanted.py`, `test_api_settings.py`.

Acceptance:
- Configure `BAZARR_URL` + `BAZARR_API_KEY` against a real Bazarr instance.
- Poller fills `bazarr_cache` within one poll interval.
- `GET /api/wanted?type=all` returns expected items with `media_path` translated to the worker's view.
- `POST /api/jobs {source:"bazarr_episode", source_ref:"123", language_code:"en"}` enqueues a job whose `media_path` was resolved correctly.

## M4 — Frontend foundation: Login, Wanted, Queue

**Goal**: a usable web UI. Log in, see the Wanted list, queue jobs, watch them progress live in Queue.

Tasks:
- Scaffold `frontend/` with Vite + TS + Tailwind + shadcn/ui per [`FRONTEND.md`](FRONTEND.md).
- Auth: Login page + `AuthGate` + protected routes.
- Theming: light / dark / auto.
- Pages: `/login`, `/wanted`, `/queue`. Layout with sidebar + theme toggle.
- Global SSE store (Zustand) wired to `/api/jobs/stream`.
- `frontend/Dockerfile` + `frontend/nginx.conf` with SSE-safe proxying.
- `docker-compose.yml`: add `frontend` service.
- (No frontend unit tests required in M4; rely on manual smoke. Add a small smoke check that `npm run build` succeeds in CI.)

Acceptance:
- `docker compose up` → `http://localhost:8080` → log in → Wanted page lists items → queue one → it appears in Queue with live-updating progress bar → reaches `done`.

## M5 — History, Logs, Settings, cost UI, auto-rescan

**Goal**: feature-complete v2. The remaining three pages, automatic Bazarr rescan after success, and the cost figures surfaced in UI.

Tasks:
- API: `/api/history`, `/api/logs`, `/api/jobs/{id}/notify-bazarr`.
- Worker: best-effort `rescan_movie` / `rescan_episode` after `done`, logged either way (stubs OK if endpoint still TBD — log a warning).
- Frontend: `/history`, `/logs`, `/settings` pages.
- Cost shown in Job detail + History aggregates.

Acceptance:
- Complete several jobs of varying lengths/languages; History shows them with correct duration and cost.
- Settings page edits persist and take effect (poll interval honoured on the next tick).
- Logs page surfaces the milestone messages (stage transitions, errors) for each job.

## M6 — Polish, docs, coverage, security pass

**Goal**: shippable v2.0.

Tasks:
- Coverage ≥ 80% on all new code paths; close gaps in worker error handling and SSE error paths.
- Update root `README.md` with v2 quickstart pointing to `dev/v2/`.
- Update v1 roadmap docs: mark Bazarr integration complete (M3+), add v2 web app as released.
- Security pass:
  - Confirm secrets never appear in logs.
  - Verify cookie flags (`HttpOnly`, `SameSite=Lax`, `Secure` behind TLS).
  - Verify input validation rejects path traversal in `media_path` when `source=manual`.
  - Verify the bootstrap refuses to start with default placeholder secrets.
- CI: align pre-commit pins with `pyproject.toml` pins (currently drift — known v1 issue).
- Make a clean checkout `docker compose up` smoke from scratch on a fresh machine.

Acceptance:
- Clean checkout → run the first-run procedure in [`DEPLOYMENT.md`](DEPLOYMENT.md) → working app, no manual fixes needed.
- All tests green, coverage report attached, lints clean.
- v2.0 release notes drafted.

## Parallelisation notes

The milestones are serial as listed. The following sub-tasks within a milestone CAN run in parallel:

- M1: db + auth + admin CLI can be developed in parallel by different agents; merge order is db → auth → API scaffold.
- M2: queue_/ + worker/ + core changes are parallelizable once `CancelToken` and `PipelineResult` shapes are agreed.
- M3: bazarr/client + bazarr/pathmap + api/routes/settings are independent.
- M4: frontend pages are independent of each other once Login + Layout + auth flow exist.
- M5: history + logs + settings pages are independent.

## Definition of done (per milestone)

Use this checklist at the end of each milestone:

- [ ] Every acceptance bullet from the milestone is demonstrated (preferably with a recorded `curl` or screenshot)
- [ ] `pytest`, `black --check`, `ruff check`, `mypy --strict` all clean
- [ ] Coverage on new modules ≥ 80%
- [ ] No new TODO/FIXME without a tracking note in the project roadmap
- [ ] CHANGELOG entry (or commit body) describes what's now possible
- [ ] All commits are conventional + `Signed-off-by`
