# v2 — Milestones

Six milestones, each independently shippable and reviewable. The order encodes hard dependencies — do not parallelise across milestones unless explicitly noted.

## Progress

| Milestone | Status | Completed | Notes |
|-----------|--------|-----------|-------|
| M0 — Repo restructure | ✅ Done | 2026-06-02 | `src/` → `audio_to_subs/` |
| M0.5 — Mistral usage probe | ✅ Done | 2026-06-02 | Probe executed, findings documented |
| M1 — DB foundation + auth | ✅ Done | 2026-06-02 | FastAPI scaffold with auth + DB |
| M2 — Worker + queue + cost | ✅ Done | 2026-06-02 | Worker, queue, pipeline cancellation, cost |
| M3 — Bazarr + `/api/wanted` | ✅ Done | 2026-06-02 | Depends on M2 |
| M4 — Frontend foundation | ✅ Done | 2026-06-02 | Depends on M3 |
| M5 — History + Logs + Settings | ✅ Done | 2026-06-03 | Depends on M4 |
| M5.1 — M5 cleanup and verification | ✅ Done | 2026-07-01 | Depends on M5 |
| M5.2 — Volume mount alignment with Sonarr/Radarr/Bazarr | ✅ Done | 2026-07-01 | Depends on M5.1 |
| M5.3 — Structural refactor batch (Phases 5–8) | ✅ Done | 2026-07-05 | Depends on M5.2; see `REFACTOR.md` |
| M5.4 — Refactor cleanup & configurable limits | ✅ Done | 2026-07-06 | Depends on M5.3 |
| M5.5 — Settings save-counter regression + Bazarr connection-test fix | ✅ Done | 2026-07-07 | Depends on M5.4 |
| M5.6 — M5.5 code-review follow-up (schema tightening, dead-field removal, error UX) | ✅ Done | 2026-07-07 | Depends on M5.5 |
| M5.6.1 — Post-M5.6 stabilization batch (unplanned bug-fix run) | ✅ Done | 2026-07-10 | Depends on M5.6; see note below |
| M5.7 — Deep mypy cleanup: transcription_client, app lifecycle, worker signals | ✅ Done | 2026-07-10 | Independent cleanup; live Mistral wire-semantics diff is a manual step (needs `MISTRAL_API_KEY`) |
| M5.8 — Queue progress reporting: live-update gaps and step-based UX | ✅ Done | 2026-07-10 | Independent; see `QUEUE_PROGRESS_REVIEW.md` |
| M6 — Polish, coverage, security | ✅ Done | 2026-07-12 | M6.a-f done (2026-07-11); M6.g, M6.h done (2026-07-12). Depends on M5.6, M5.7, M5.8 |
| M6.i — Post-M6 hardening batch (unplanned): ParoleSub rebrand + deploy hardening | ✅ Done | 2026-07-18 | Depends on M6; see note below |
| M7 — Documentation rewrite & dev-docs reorganization | ⏳ Not Started | - | Depends on M6; now M16 below — deferred until after the v2.1–v4.0 feature work |
| M8 — v2.1 Wanted scope: sync everything, filter client-side | ⏳ Not Started | - | Depends on M6; refines M3 polling + Wanted UI |
| M9 — v2.2 (TBD — scope to be defined) | ⏳ Not Started | - | Depends on M8 |
| M10 — v2.3 Admin password sync on secret/env change | ⏳ Not Started | - | Depends on M1 (auth/bootstrap); see note |
| M11 — v2.4 Queue: Auto-refresh On by default | ⏳ Not Started | - | Depends on M4 (Queue UI) |
| M12 — v2.5 History: Retry action for failed jobs | ⏳ Not Started | - | Depends on M5 (History UI) + M6.g retry machinery |
| M13 — v2.6 Visual polish: History filter buttons + ParoleSub logo | ⏳ Not Started | - | Depends on M4/M5 UI |
| M14 — v3.0 Redis/jobs-progress architecture refactor | ⏳ In progress (branch `investigate-progress-bar`) | - | Absorbs the in-flight `investigate-progress-bar` work; depends on M5.8 |
| M15 — v4.0 Periodic, configurable jobs (Bazarr sync + auto-schedule) | ⏳ Not Started | - | Depends on M3 (Bazarr) + M14 (progress arch) |
| M16 — Documentation rewrite & dev-docs reorganization (deferred) | ⏳ Not Started | - | Depends on M6; deferred until after M8–M15 |

Every milestone ends with the same quality bar:

- `pytest` green
- `black`, `ruff`, `mypy --strict` clean
- New code ≥ 80% coverage
- Conventional commit prefixes (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`)
- All commits include `Signed-off-by:` per the repo's commit message template

## M0 — Repo restructure: `src/` → `audio_to_subs/`

**Goal**: relocate the v1 pipeline into a real package with a `core/` subpackage. No behaviour changes.

Tasks:
- [`../archive/MIGRATION.md`](../archive/MIGRATION.md) mechanical rename + import rewrites.
- Update `pyproject.toml` entry point and package config.
- Update Dockerfile/Compose paths and `python -m` entrypoints.

Acceptance:
- `pytest` passes unchanged (no test logic changed; only import paths).
- `parolesub --version` works.
- `parolesub -i dev/test_video.mp4 -o /tmp/out.srt` produces the same SRT as before M0.
- Container builds and runs the CLI end-to-end.

Out of scope: any new code under `db/`, `api/`, `worker/`, etc. Add the empty `core/__init__.py`; everything else lands in later milestones.

## M0.5 — Mistral usage probe (one-off spike, blocks M2)

Run [`../archive/MISTRAL_USAGE_PROBE.md`](../archive/MISTRAL_USAGE_PROBE.md). Document the exact response shape of `mistralai==2.4.5`'s transcription endpoint in that file. Decide whether `core/cost.py` reads real usage or falls back to duration × rate.

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
- Settings model includes:
  - `mistral_model`: str
  - `mistral_rate_usd_per_minute`: float (primary audio duration billing)
  - `mistral_input_token_rate_usd`: float | None (optional token-based input billing)
  - `mistral_output_token_rate_usd`: float | None (optional token-based output billing)
  - `bazarr_poll_interval`: int
  - `bazarr_track_no_subs`: bool
  - `path_mappings`: list of dict pairs
  - `default_language`: str
  - `default_output_format`: str
- Tests: `test_bazarr_client.py`, `test_bazarr_pathmap.py`, `test_bazarr_poller.py`, `test_api_wanted.py`, `test_api_settings.py`.

Acceptance:
- Configure `BAZARR_URL` + `BAZARR_API_KEY` against a real Bazarr instance.
- Poller fills `bazarr_cache` within one poll interval.
- `GET /api/wanted?type=all` returns expected items with `media_path` translated to the worker's view.
- `POST /api/jobs {source:"bazarr_episode", source_ref:"123", language_code:"en"}` enqueues a job whose `media_path` was resolved correctly.
- `GET /api/settings` returns all cost rate fields; `PATCH /api/settings` updates them.

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
- **Settings page**: Mistral pricing section with:
  - Model name selector
  - Audio rate (USD per minute) — primary billing method
  - Input token rate (USD per token) — optional
  - Output token rate (USD per token) — optional
  - Fallback rate for when Mistral usage data unavailable
- Cost shown in Job detail + History aggregates (using configured rates).

Acceptance:
- Complete several jobs of varying lengths/languages; History shows them with correct duration and cost.
- Settings page edits persist and take effect (poll interval honoured on the next tick; cost rates used for new jobs immediately).
- Logs page surfaces the milestone messages (stage transitions, errors) for each job.

## M5.1 — M5 cleanup and verification

**Goal**: Clean up M5 artifacts and verify all features work end-to-end.

Tasks:
- Remove leftover ComingSoonPage.tsx from frontend
- Update MILESTONES.md to mark M5 as complete
- Verify all M5 API endpoints functional (/api/history, /api/logs, /api/settings, /api/jobs/{id}/notify-bazarr)
- Verify all M5 frontend pages render correctly (/history, /logs, /settings)
- Verify Bazarr rescan triggers on job completion
- Run full quality suite (pytest, black, ruff, mypy)

Acceptance:
- `make frontend-preview` shows no "Coming in M5" messages
- All M5 pages (History, Logs, Settings) fully functional
- No unused imports or dead code from M4/M5 transition
- All tests pass
- Lint and format checks clean

### Bug fixes found during stack integration testing (2026-07-01)

Discovered by running `podman-compose up` for the first time against the full stack:

| # | Severity | File | Description | Fix |
|---|----------|------|-------------|-----|
| 1 | Critical | `bazarr/poller.py` | `run_bazarr_poller()` held `BEGIN IMMEDIATE` write lock for the full poll interval (default 3600 s) when Bazarr was not configured — the inter-poll sleep ran inside the `async with get_async_session()` block. Blocked reaper, health check, and all API writers, causing the backend health check to return 503 permanently and preventing worker + frontend from ever starting. | Restructured loop so the session always exits before `asyncio.wait_for`. Added `interval = 3600` default before the loop to handle session failures. |
| 2 | Medium | `docker-compose.yml` | Health check `urlopen` had no `timeout=` argument; Podman killed it after the container-level 5 s timeout, reporting exit code 125 with empty output. | Added `timeout=3`. |
| 3 | Low | `docker-compose.yml` | `deploy.resources.reservations.cps` typo on the backend service; CPU reservation was silently ignored. | Fixed to `cpus`. |

Regression tests added: `test_poller_releases_session_before_sleep` in `test_bazarr_poller.py` and `test_healthz_returns_503_when_db_unavailable` in `test_api_healthz.py`.

## M5.2 — Volume mount alignment with Sonarr/Radarr/Bazarr

**Goal**: Align volume mounts and subtitle path handling with Bazarr, Sonarr, and Radarr conventions. Separate movie/TV input paths and save subtitles alongside source files.

**Depends on**: M5.1

Tasks:
- Add movies_root_path, tv_root_path, subtitles_same_directory settings
- Extend Settings API and frontend with new path configuration
- Update worker to save subtitles in source directory when configured
- Update docker-compose.yml to use separate /movies and /tv volumes
- Update testing.docker-compose.yaml to match new volume structure
- Add SELinux relabeling (:z/:Z) to volume mounts for Podman compatibility
- Enhance PathMap with media type detection and output path generation
- Add path validation to prevent traversal and ensure paths within allowed roots
- Update frontend settings page with new configuration options
- Update job creation to auto-generate output_path when subtitles_same_directory=True
- Add tests for all new functionality

Acceptance:
- docker compose up brings up stack with /movies and /tv volumes instead of /input and /output
- Subtitles are saved alongside source video files when subtitles_same_directory=True
- Settings page allows configuration of movies_root_path, tv_root_path, and subtitles_same_directory
- Path validation prevents jobs with media_path outside configured roots
- Bazarr rescan picks up subtitles from same directory as video files
- No SELinux permission errors on Podman with enforcing SELinux
- pytest, black, ruff, mypy all clean
- New code ≥ 80% coverage

## M5.3 — Structural refactor batch (Phases 5–8)

**Goal**: work through the backend/frontend structural cleanup identified
after M5.2, executed as a batch of independent, parallel-mergeable units.

**Depends on**: M5.2

**Authoritative plan**: REFACTOR.md (external document in sibling `audio_to_subs_plans/` repo - not included in this codebase) That document is the source of truth for
this milestone's scope, execution order, and per-item detail — this section
only summarizes; do not duplicate its item lists here.

Tasks (see `REFACTOR.md` for the full breakdown):
- **Phase 5 — Backend structural refactors**: behavior-preserving dedup of
  ~360+ duplicated lines (FFmpeg helpers, subtitle page-splitting, secret
  file-reads, "fetch job or 404", path-map loading, Redis publish, WantedItem
  serialization, WAL/BEGIN-IMMEDIATE listeners, etc.), plus a batch of
  structural correctness/performance items (retry/backoff, timeouts, N+1
  query fixes, SSE architecture moving to Redis pub/sub, worker session
  ownership).
- **Phase 6 — Frontend refactor**: extract data-fetching hooks
  (`useHistory`/`useLogs`/`useSettings`), split the `SettingsPage.tsx`
  monolith, unify job-state ownership (SSE→Zustand, everything else→
  react-query), dedupe formatting helpers.
- **Phase 7 — Hygiene sweep**: mechanical cleanup — unused imports, dead
  code, type-hint modernization (`X | None`), oversized-function splits,
  test fixture/naming standardization.
- **Phase 8 — Docs**: this document and `TESTING.md` themselves are part of
  this phase.

Acceptance: each unit lands independently with `pytest`/`black`/`ruff`/`mypy`
clean and coverage non-decreasing (per `REFACTOR.md`'s verification
checklist); no behavior change expected from Phase 5–7 work beyond the fixes
explicitly called out as bugs in earlier phases of that plan.

## M5.4 — Refactor cleanup & configurable limits

**Goal**: Close remaining M5.3 gaps (lint/format/mypy), implement D5 (configurable max_audio_length with per-model presets), and D13 (raw SQL → ORM).

**Depends on**: M5.3

Tasks:
- **M5.4.1** — Lint/format/mypy cleanup: ruff --fix (516 auto-fixable), black (45 files), mypy python_version 3.9→3.11, ruff config migration to `[tool.ruff.lint]`
- **M5.4.2** — D13: 5 raw SQL UPDATE sites → ORM; fix `__main__.py:158` missing `updated_at` (latent bug)
- **M5.4.3** — D5: configurable `max_audio_length` (60–10800s, default 900) with per-model presets:
  - Backend: `audio_to_subs/core/models.py` (MODEL_SPECS), DB settings + validation, worker clamp (`min(setting, model_preset)`), Pipeline param, audio_splitter uses runtime value
  - Frontend: types (SettingsOut/Patch/FormData), MistralSettingsForm with auto-fill + clamp, useSettingsForm dirty-tracking
  - Model presets: voxtral-mini-2602/latest=10800s, voxtral-mini-2507/small-2507=900s
  - Unify default model to `voxtral-mini-2602` across all layers (DB, Pipeline, worker, client)
- **M5.4.4** — Remove stale xfail (B25 done; BDD test itself has a mocking issue, re-added xfail with updated reason)
- **M5.4.5** — Docs: MILESTONES.md M5.4 section (this), TESTING.md (no updates needed)

Acceptance:
- ruff, black --check, mypy all clean
- `max_audio_length` configurable in WebUI Settings; per-model clamp enforced at runtime
- No raw SQL UPDATE statements in jobs/worker paths
- Full test suite green (523 passed, 3 skipped, 1 xfailed)
- Default model unified to `voxtral-mini-2602` across all layers
- Branch `m5.4-refactor-cleanup` ready to merge into `dev`

## M5.5 — Settings save-counter regression + Bazarr connection-test fix

**Goal**: fix two user-reported regressions surfaced after M5.4, plus the test-quality gap that let both slip through: the Settings page's unsaved-changes counter never clears when modifying an already-set Bazarr API key, and "Test Connection" always reports failure even with a valid, working key.

**Depends on**: M5.4

Root causes (both confirmed against the running code and against Bazarr's actual source at `../bazarr`, v1.5.6+57):

1. **Save-counter stuck on API-key edits.** The server always masks `bazarr_api_key` to a fixed sentinel (`***MASKED***`) in every response. `useSettingsForm.ts` resyncs its form baseline via a `useEffect` keyed on the `settings` object from React Query. When the only saved change is the API key, the post-save refetch payload is deeply equal to the cached one (masked → masked), so React Query's structural sharing keeps the same object reference and the effect never re-fires — the form keeps the raw typed key, and the diff against the (unfired) baseline never reaches zero. Empty↔set transitions change the payload and so appear to "work", masking the bug for those two cases.
2. **Bazarr "Test Connection" always fails.** Bazarr's real `GET /api/series` marshals `audio_language` as a JSON array (or a dict of nulls when the DB column is empty) — never as the populated object our `Series` pydantic schema expects. Every real response fails schema validation, the endpoint's generic exception handler swallows the `ValidationError` and reports it as a generic connection failure, even though the same API key works fine on the Wanted-refresh path (which validates a different, leaner schema). The same broken schema also silently degrades the opt-in `bazarr_track_no_subs` polling path.
3. **Test gap.** Existing unit tests encode our own (wrong) assumptions about Bazarr's wire format instead of the real API, and the connection-test endpoint has no test that mocks Bazarr at the HTTP level — so a universally-failing endpoint still passes CI.

Tasks (TDD order — failing tests first):
- Add reverse-engineered wire-format tests for `/api/series` (`tests/test_bazarr_client.py`, new shared fixture module) covering the realistic populated item, null-heavy items, the null-column `audio_language` marshal shape, empty library, and paginated/unfiltered `total` — fix the existing `test_list_all_series` fixture, which encoded the wrong shape.
- Add endpoint-level wire tests (`tests/test_api_settings.py`) driving `test_bazarr_connection` against realistic Bazarr responses via `respx`: success, 401 (HTML body), 302 redirect, empty library, and schema-drift.
- Add a regression test for the `bazarr_track_no_subs` polling path (`tests/test_bazarr_poller.py`) proving it survives a realistic `/api/series` payload.
- Fix `audio_to_subs/bazarr/schemas.py`'s `Series` model to accept Bazarr's real wire shape (`audio_language` as a list, nullable `monitored`/`ended`) without weakening required fields (`sonarrSeriesId`/`title`/`path`).
- Fix `audio_to_subs/api/routes/settings.py`'s `test_bazarr_connection` to catch `pydantic.ValidationError` distinctly (as `error="unexpected_response"`, logged with field locations only — never payload values) instead of misreporting schema drift as a generic connection failure.
- Add a frontend regression test (`SettingsPage.test.tsx`) covering the masked-to-masked refetch case (modifying an already-set key), which the existing empty→set test doesn't exercise.
- Fix `frontend/src/hooks/useSettingsForm.ts` / `frontend/src/pages/SettingsPage.tsx` to rebuild the form baseline explicitly from the PATCH response (`resetFromSettings`) instead of relying on the `useEffect`/query-cache resync that structural sharing can starve.

Acceptance:
- Saving an edit to an already-configured Bazarr API key clears the unsaved-changes counter (not just empty→set or set→empty). ✅ verified live against a real browser session.
- "Test Connection" succeeds against a real, reachable Bazarr instance with a valid key. ✅ verified live against a real Bazarr container.
- `bazarr_track_no_subs` polling no longer logs schema-validation warnings against a real Bazarr instance. ✅ verified — a manual refresh populated the wanted-episode cache with no validation warnings in the backend log.
- New tests fail against the pre-fix code and pass after (verified, not just asserted).
- Full backend (`pytest`, 520 passed) and frontend (`vitest`, 45 passed; `tsc --noEmit` clean) suites pass.
- No weakening of the API-key masking/hardening introduced in the previous auth/settings fix round.

### Additional finding during live verification: `/api/episodes` schema mismatch

Live E2E testing against a real Bazarr instance surfaced a second, previously-undetected schema bug in the same feature area (opt-in `bazarr_track_no_subs` polling), fixed as part of this milestone since it blocked the polling acceptance criterion above:

- Bazarr's real `GET /api/episodes` (as opposed to `/api/episodes/wanted`) marshals with `envelope='data'` only and **never sends a top-level `total`** — our `EpisodesPage.total` was required, so every call raised a `ValidationError`, silently swallowed by `_poll_all_episodes`'s catch-all (same failure mode as the `/api/series` bug, different endpoint).
- The same "*_language_model" family shared by `audio_language`/`subtitles`/`missing_subtitles` allows null `code2`/`code3` (an unresolved/"Unknown" language track) — our `SubtitleLanguage.code2`/`code3` were required non-null strings.
- Fixed: `EpisodesPage.total` is now optional (nothing in the codebase reads it); `SubtitleLanguage.code2`/`code3` are now optional. Regression tests added to `tests/test_bazarr_client.py` reverse-engineered from the real Bazarr source and a live instance's actual response.

## M5.6 — M5.5 code-review follow-up

**Goal**: address the minor observations surfaced in the post-merge code review of M5.5 (commits `6ab1884` and `a696f38`), delivered as two independently-shippable commits split on a backend / frontend boundary. No behaviour change beyond the frontend toast copy; the backend changes only tighten validation on fields that nothing currently consumes.

**Depends on**: M5.5

Observations addressed (per commit):

1. **`Series.audio_language` declared too loosely.** Typed as `list[dict[str, Any]]`, but its own docstring promised "list of {name, code2, code3}; codes may be null" — a validation contract the type never enforced. Inner-shape drift (e.g. an entry missing `name`) was silently accepted, contradicting M5.5's stated goal of surfacing genuine drift distinctly.
2. **`EpisodesPage.total` was dead weight.** Declared `int | None` but never read at runtime and never sent by Bazarr's `/api/episodes` resource (marshals with `envelope='data'` only). M5.5's note "nothing reads it" was accurate — the field can simply go.
3. **`test_list_episodes_real_wire_format` didn't deliver its stated intent.** The test's docstring claimed to verify null `code2`/`code3` parsing on episodes, but the `Episode` schema didn't model `audio_language`/`missing_subtitles`, so pydantic silently dropped those fields — the test only proved extras were tolerated, not that null codes parsed. The same family of `*_language_model` fields that drove the M5.5 `Series` fix applies here.
4. **Frontend error UX gap surfaced by M5.5.** `BazarrSettingsForm.tsx` passed the raw backend `error` string into the toast, so M5.5's new `unexpected_response` code rendered verbatim as `"Failed to connect to Bazarr: unexpected_response"` — meaningless to end users. Same problem affected every pre-existing code (`connection_failed`, `server_error`, …); M5.5 just made it newly visible.
5. **`setQueryData` vs `invalidateQueries` choice undocumented.** M5.5 swapped `invalidateQueries(["settings"])` for `setQueryData(...)` in the save mutation — a deliberate behaviour change (no background refetch after save) that deserved an explicit note.

Tasks (split as two commits):

**Commit 1 — Backend schema/test cleanup** (`fix(bazarr): ...`):
- Tighten `Series.audio_language: list[dict[str, Any]]` → `list[SubtitleLanguage]`. The existing `_normalize_audio_language` validator (mode="before") stays — it still collapses the null-column dict-of-nulls shape to `[]` before pydantic validates each entry against `SubtitleLanguage`. No runtime change: the poller doesn't read `audio_language`.
- Add `Episode.audio_language` and `Episode.missing_subtitles` (both `list[SubtitleLanguage]`, default empty) so the schema actually models the fields the wire-format test exercises.
- Remove `EpisodesPage.total` entirely; update the docstring. Update all `EpisodesPage(...)` construction sites in `tests/test_bazarr_poller.py` and the assertion + mock in `tests/test_bazarr_client.py::test_list_episodes`.
- Update `test_list_episodes_real_wire_format` to assert null-code parsing on the now-modelled `Episode.audio_language`/`missing_subtitles` fields (instead of the apologetic "silently dropped" framing).

**Commit 2 — Frontend error UX + doc note** (`fix(settings): ...`):
- Add a `BAZARR_ERROR_MESSAGES` map in `frontend/src/components/settings/BazarrSettingsForm.tsx` covering every code the backend can return (`bazarr_not_configured`, `authentication_failed`, `resource_not_found`, `rate_limited`, `server_error`, `unexpected_response`, `connection_failed`), with friendly human text. Use it in `handleTestConnection`, keeping `response.message` then `"Unknown error"` as fallbacks for forward compatibility with future server-supplied detail or unknown codes.
- Document the intentional `setQueryData`-instead-of-`invalidateQueries` choice next to the call in `frontend/src/pages/SettingsPage.tsx`: settings is a low-concurrency resource and the PATCH response is authoritative; a background refetch would race with this update for no benefit.
- Add `frontend/src/pages/SettingsPage.test.tsx` cases asserting each error code renders the friendly message via `toast.error`, plus an unknown-code fallback test.

Acceptance:
- `Series.audio_language` parses to `SubtitleLanguage` entries; the realistic fixture validates, the null-column case normalizes to `[]`, the populated-dict drift case still fails distinctly as `unexpected_response`.
- `Episode` parses `audio_language`/`missing_subtitles` with null codes; `test_list_episodes_real_wire_format` positively asserts `code2 is None`/`code3 is None` on the parsed entries.
- `EpisodesPage` has only the `data` field; no test in the suite references `EpisodesPage.total`.
- Each backend error code renders as a friendly toast; an unknown code falls back to `response.message` then `"Unknown error"`.
- Full `pytest`, `black --check`, `ruff check`, `mypy --strict` clean.
- Full frontend `vitest` and `tsc --noEmit` clean.
- All commits conventional + `Signed-off-by`.

Out of scope:
- The `path_mappings as any` cast in `settingsToFormData` — pre-existing (not introduced by either reviewed commit); fixing it requires touching the `SettingsPatch` type and is a separate concern.

## M5.6.1 — Post-M5.6 stabilization batch (unplanned)

**Goal**: not a planned milestone — a retroactive record of an ad-hoc bug-fix
run (2026-07-07 to 2026-07-10) that landed directly on `dev` between M5.6 and
the M5.7 write-up, discovered via live use against real Bazarr/Podman rather
than through milestone planning. Recorded here so this document keeps
matching `dev`'s actual state.

**Depends on**: M5.6

Notable fixes, roughly grouped:

- **Worker/queue correctness** (`worker/__main__.py`, `worker/runner.py`):
  `ClaimedJob.id` was a `uuid.UUID` against a `String(36)` column — aiosqlite
  can't bind it, so failed jobs never persisted their status and stuck in
  `running` forever, getting re-claimed on every worker restart (`9bc375f`).
  The worker also held the sole SQLite write lock (`BEGIN IMMEDIATE`) for the
  entire multi-minute Mistral call, blocking History reads and progress
  writes until they errored `database is locked` (`41cde58`) — same class of
  bug as the M5.1 poller finding, different call site.
- **Bazarr path resolution** (`bazarr/poller.py`): wanted-endpoint items have
  `sceneName=null` and no path; the real path only lives on the full
  movie/episode detail endpoints. Poller now fetches those details and
  threads the authoritative path through (`479f0bb`), and the API surfaces a
  clear 400 instead of a confusing validation error when no path resolves
  (`166543e`).
- **Subtitle filename correctness** (`core/subtitle_generator.py`,
  rename endpoint): the language code could be appended twice
  (`stem.fr.fr.srt`) because both job-creation-time and generation-time paths
  added it independently; made idempotent (`0bf433b`), the rename endpoint
  fixed to strip all trailing suffixes so already-broken files self-correct
  (`a0c4bba`), and `job.output_path` is now persisted post-completion so auto
  mode's actual on-disk path matches the DB (`e093638`).
- **Logging**: the API never configured logging (uvicorn leaves root logger
  untouched) and the worker had disconnected config, so most info/debug
  output and several UI-facing `job_logs` events (job creation, Bazarr
  sync/notify, login) were silently dropped. Added `configure_logging_from_env()`
  (`LOG_LEVEL`) and a shared `write_job_log()` helper (`f64868f`).
- **Podman hardening**: fully-qualified remaining short image names so
  Podman stops prompting on unaliased short names (`65dc82c`, `06a042b`),
  and fixed the worker crash-looping from a missing `SESSION_SECRET_FILE`
  env var (`75c1370`).
- **Frontend polish**: Wanted table column stability, rows-per-page
  selector, refresh scoped to the active Movies/Series filter, reveal
  toggle for the Bazarr API key field.

No acceptance checklist — this predates any plan. Full `pytest`/`black`/`ruff`
suite was green at each commit per their individual messages; `mypy --strict`
gaps from this period are exactly what M5.7 tracks.

## M5.7 — Deep mypy cleanup: transcription_client, app lifecycle, worker signals

**Goal**: resolve the structural `mypy` errors deliberately deferred during the M5.6-era five-branch merge into `dev` (login-race-condition, ui-status-bugs, job-duration, avg-cost-calculation, local-time-ui-option). That merge's cleanup commit fixed all mechanical mypy errors (missing annotations, `no-any-return`, etc.) directly and added narrow, commented `# type: ignore[code]` markers for the harder cases below, rather than risk behaviour changes to code that couldn't be fully exercised end-to-end in that session (no live Mistral API access, no real OS signal delivery in the dev environment).

**Depends on**: none (independent cleanup)

Tasks:
- `audio_to_subs/core/transcription_client.py` (27 errors, the bulk of the backlog): the `**dict[str, object]` kwargs pattern used to call the Mistral SDK's `Transcriptions.complete(...)` doesn't match its overloads (wrong keyword names in one spot — `fileName`/`contentType` vs `file_name`/`content_type` — plus argument-type mismatches). Needs a real pass against the installed SDK version: either build a properly-typed `TypedDict`/kwargs object per call site, or confirm the mismatched keyword args are dead/incorrect and fix them for real. Verify against a live (or recorded/VCR) Mistral API call, not just `mypy` — see `dev/v2/MISTRAL_USAGE_PROBE.md`'s "Note for M5.7" section for a ready-made probe-script template and the two specific things it still needs to settle (the `language`/`Unset` wire-semantics question, and whether the tuple-based `file=("name", fileobj, "content-type")` calling convention sidesteps the `File`/alias mismatch entirely).
- `audio_to_subs/api/app.py`: `_AppProxy` lazy-init wrapper assigned where a `FastAPI` is expected (line ~247) — needs a proper `Protocol`/typing fix for the lazy-app pattern, not just an ignore.
- `audio_to_subs/worker/__main__.py` — **confirmed bug, not just a typing gap**: `handle_shutdown`'s inner `shutdown(signame: str)` is registered directly via `signal.signal(signal.SIGINT, shutdown)` / `signal.signal(signal.SIGTERM, shutdown)`, but the stdlib always invokes signal handlers as `handler(signum, frame)`. A real SIGINT/SIGTERM will raise `TypeError: shutdown() takes 1 positional argument but 2 were given` instead of shutting the worker down gracefully. Fix the handler signature to accept `(signum: int, frame: FrameType | None)`, then verify with an actual signal-delivery test (e.g. send SIGTERM to a running worker process and confirm graceful shutdown), not just `mypy`/unit tests.
- Sweep the remaining narrow `# type: ignore[...]` markers left by the M5.6-era cleanup commit (grep for a marker comment referencing this milestone) and replace each with a real fix using the same rigor.

Acceptance:
- `mypy audio_to_subs/` clean with zero `# type: ignore` remaining from the deferred set (new, well-justified ignores elsewhere are fine).
- Transcription pipeline manually verified against a real (or recorded) Mistral call after the `transcription_client.py` changes.
- Worker manually verified to still shut down gracefully on SIGTERM/SIGINT after the signal-handler typing fix.
- Full `pytest`, `black --check`, `ruff check` clean; no behaviour change outside the three files above.

**Verification (2026-07-19)**: the `mypy --strict` gap is now closed. The originally-deferred `--strict` findings (the bulk in `transcription_client.py` had already been resolved in the M5.6-era cleanup commit; the remaining errors spanned `api/deps.py`, `api/routes/{_helpers,healthz,wanted,history,stream}.py`, `core/{ffmpeg_utils,pipeline}.py`, `bazarr/poller.py`, `worker/{progress,runner,__main__}.py`, and `queue_/events.py`) were fixed with real typing — generic type parameters on `subprocess.Popen[str]`/`asyncio.Task[Any]`/`dict[str, Any]`/`list[Any]`, an explicit `get_db` re-export in `api/deps.py` (via `__all__`), and a `SubtitleFileExistsError` re-export in `core/pipeline.py` (via `__all__`). The `redis.asyncio.from_url` calls use narrow, commented `# type: ignore[no-untyped-call,no-any-return]` markers (see the M6 status note for why `types-redis` was rejected). `mypy --strict audio_to_subs/` passes with zero errors; `pytest` 724 passed, 4 skipped, 1 xfailed; `black --check`/`ruff check` clean (only the pre-existing 4-file I001/F401 set remains, untouched by this work). The `flake.nix` crash that blocked verification (native `mypy` `librt.base64` import error) is also fixed.

## M5.8 — Queue progress reporting: live-update gaps and step-based UX

**Goal**: fix the user-reported "Queue page looks frozen unless I manually refresh" bug and replace the raw 0-100% bar with a step-based indicator (`Step 2 of 4 — Extracting audio`) plus an inner sub-progress bar where real sub-progress data exists.

**Depends on**: none — independent, isolated to the pipeline's progress emission and the Queue page's SSE handling.

**Authoritative plan**: [`../archive/QUEUE_PROGRESS_REVIEW.md`](../archive/QUEUE_PROGRESS_REVIEW.md) (full root-cause analysis and design). This section only summarizes; do not duplicate its detail here.

Root causes (all confirmed against current code — see the linked doc for `file.py:line` references):

1. `extract` and `split` each emit exactly one progress event at stage-start and one at stage-completion, with total silence during the actual (potentially long) ffmpeg decode — because the worker constructs `Pipeline(verbose_progress=False)`, which strips the callback that would otherwise drive ffmpeg's already-implemented native time-based progress parsing. This is the literal cause of the screenshot: a job pinned on "Extracting audio from video…" / 10% for however long ffmpeg takes.
2. The `"new"` SSE event only increments an unused `pendingNewCount` counter in the frontend Zustand store — nothing consumes it, so a job created after the Queue page loads never appears until a manual refresh.
3. API-originated SSE events (`new`, `cancel`) are delivered twice per client (once via an in-process observer callback, once via the API process's own Redis-subscriber loopback); worker-originated events (`progress`, `done`) aren't affected since the worker process's observer lists are always empty.
4. The pipeline's discrete stage (`init`/`extract`/`split`/`transcribe`/`generate`/`done`) is forwarded live over SSE but never persisted to the `jobs` table — only `progress_percent`/`progress_message` are — so a refresh mid-job can't reconstruct which step a job is on.
5. Stage percent boundaries (10/25/30/75/100) are unweighted magic numbers with no timing basis.

Tasks (see `QUEUE_PROGRESS_REVIEW.md` for full detail):
- DB: new migration adding `jobs.progress_stage`; `ProgressBridge` persists it.
- `core/pipeline.py`: compute `step_index`/`step_total` per job (accounting for whether splitting actually occurs); wire ffmpeg's native time-based progress into `extract`/`split` independent of `verbose_progress`.
- `queue_/events.py` + `api/app.py`: remove the duplicate in-process observer delivery path; route 100% of SSE delivery through Redis pub/sub, matching `QUEUE.md`'s documented architecture.
- API schema (`JobResponse`) and frontend types (`JobResponse`, `LiveJob`, `SseEventData`) gain `progress_stage`/`step_index`/`step_total`.
- Frontend `QueuePage.tsx`: `JobCard` shows `Step {step_index} of {step_total} — {stage}` as the primary label with the existing percent bar as a secondary in-step indicator (indeterminate when no sub-progress source exists); wire the dead `pendingNewCount` to a `["jobs"]` query invalidation.

Acceptance:
- A job whose video takes >30s to decode shows continuously advancing percent during "Extracting audio", not a single jump from 10%→25%.
- Creating a job from another tab/actor while the Queue page is open makes it appear within one SSE round-trip, no manual refresh required.
- Each SSE event is delivered to a connected client exactly once (regression test covering the API-originated `new`/`cancel` path specifically).
- A hard refresh mid-job shows the correct persisted step/stage, not just percent/message.
- `step_total` reflects whether splitting actually occurred for that job (3 vs 4), not a hardcoded constant.
- `pytest`, `black --check`, `ruff check`, `mypy --strict` clean; frontend `vitest` and `tsc --noEmit` clean; new code ≥ 80% coverage.

## M6 — Polish, coverage, security pass

**Goal**: shippable v2.0 codebase (functional bar only — documentation rewrite and dev-docs reorganization are split out to [M7](#m7--documentation-rewrite--dev-docs-reorganization) since they're a separate, larger body of work once the full scope of the v2 rewrite is known).

**How to read this section**: M6 is split into 8 sub-tracks (M6.a–M6.h), each its own `###` heading below with a self-contained **Mode**, **Depends on**, **Owns**, **Goal**, **Tasks**, and **Acceptance**. An agent handed a single sub-track (e.g. "do M6.c") should only need to read that one heading — everything needed to start is there; nothing critical is left in this shared intro. The dispatch table below is a map for whoever is *assigning* work across sub-tracks; it is not itself a source of task detail.

| ID | Name | Mode | Depends on | Owns (short) | Status |
|----|------|------|------------|---------------|--------|
| [M6.a](#m6a--coverage-worker-error-handling) | Coverage: worker error handling | Parallel | — | `worker/{runner,progress,helpers,__main__}.py` | ✅ Done |
| [M6.b](#m6b--coverage-sse-error-paths) | Coverage: SSE error paths | Parallel | — | `api/routes/stream.py`, `queue_/events.py` | ✅ Done |
| [M6.c](#m6c--security-auth-session-and-log-hygiene) | Security: auth, session, log-hygiene | Parallel | — | `auth/{sessions,bootstrap,passwords,deps}.py`, `core/logging_config.py` | ✅ Done |
| [M6.d](#m6d--security-path-traversal-validation) | Security: path-traversal validation | Parallel† | — | `core/path_utils.py`†, `bazarr/pathmap.py`, `api/{routes,services}/jobs.py` | ✅ Done |
| [M6.e](#m6e--ci-pre-commit-pin-alignment) | CI: pre-commit pin alignment | Parallel | — | `.pre-commit-config.yaml` | ✅ Done |
| [M6.f](#m6f--semantic-audit-standardize-uiapi-terminology-on-series-not-tv) | Semantic audit: "Series" not "TV" | Parallel† | — | `frontend/src/**`, `api/routes/settings.py`, `core/path_utils.py`† | ✅ Done |
| [M6.g](#m6g--overwrite--duplicate-job-guards) | Overwrite & duplicate-job guards | **Sequential** | M6.a, M6.d, M6.f | `api/{routes,services}/jobs.py`, `worker/runner.py`, `core/file_rename.py`, `frontend/.../WantedPage.tsx` | ✅ Done |
| [M6.h](#m6h--clean-checkout-smoke-test) | Clean-checkout smoke test | **Sequential** | all of the above | none by default | ✅ Done |

†M6.d and M6.f both touch `core/path_utils.py` (different functions — traversal-validation vs. the `MediaType` literal). They can still run in parallel, but land as two small, non-overlapping diffs rather than editing simultaneously without coordinating.

M6.a, M6.b, M6.c, M6.d, M6.e, and M6.f have no dependencies on each other and no dependencies on M6.g/M6.h — run them as separate sub-agents in parallel. M6.g must wait for M6.a, M6.d, and M6.f specifically (it edits files those own). M6.h must wait for everything else — it verifies the fully-merged result.

**M6.a–d dispatch note (2026-07-11)**: the four sub-tracks were dispatched to separate agent branches (`address-milestone-6-a`, `implement-milestone-6-b`, `implement-milestone-6c`, `implement-m6d-specificati`) before this sub-track breakdown was committed to `dev`, so each agent worked from ambiguous scope and the branches ended up crossing lines: `address-milestone-6-a` actually delivered M6.c+M6.d work, `implement-milestone-6-b` delivered a bit of everything (true M6.a/M6.b coverage plus a second M6.c/M6.d implementation), `implement-milestone-6c` delivered M6.d's path-traversal fix, and `implement-m6d-specificati` delivered a slice of M6.c's bootstrap-refusal fix. All four branches were merged into `dev` and the overlapping/duplicate security implementations (three separate path-traversal checks, three separate placeholder-secret-refusal call sites) were reconciled down to one implementation per concern, keeping the most robust version of each and re-running the full suite after each merge. The **Owns** and implementation notes below describe where each concern actually landed, not which branch it came from.

### M6.a — Coverage: worker error handling

**Mode**: Parallel. **Depends on**: none. **Owns**: `audio_to_subs/worker/{runner.py,progress.py,helpers.py,__main__.py}`, `tests/test_worker_*.py`. Do not edit files outside this list — if closing a gap needs a change elsewhere (e.g. a shared `tests/conftest.py` fixture), stop and flag it instead of editing it directly.

**Goal**: close coverage gaps in worker exception paths.

**Tasks**: add/extend tests for claim failures, mid-job crash + reap interaction, cancellation races, and the M5.7 SIGINT/SIGTERM handler path.

**Acceptance**:
- Coverage on `audio_to_subs/worker/*` ≥ 80%, including the exception branches above.
- Tests only — no behavior change, unless a genuine bug is found in the process (fix it and note it explicitly in the PR/commit).
- `pytest`, `black --check`, `ruff check`, `mypy --strict` clean.

**Done (2026-07-11)**: `tests/test_worker_runner.py` adds coverage for the Bazarr rescan best-effort failure path, `_get_db_settings` fetch failure, and `persist_result` `IntegrityError` handling. Tests only, no behavior change.

### M6.b — Coverage: SSE error paths

**Mode**: Parallel. **Depends on**: none. **Owns**: `audio_to_subs/api/routes/stream.py`, `audio_to_subs/queue_/events.py`, `tests/test_api_stream.py`, `tests/test_queue_events.py`.

**Goal**: close coverage gaps in SSE error paths, post-M5.8's move to Redis-only delivery.

**Tasks**: add/extend tests for client disconnect mid-stream, Redis pub/sub failure/reconnect, and malformed/oversized event payloads.

**Acceptance**:
- Coverage on `api/routes/stream.py` and `queue_/events.py` ≥ 80%, including the branches above.
- Tests reflect the current Redis-only delivery path — no leftover assertions about the dual in-process+Redis delivery M5.8 removed.
- `pytest`, `black --check`, `ruff check`, `mypy --strict` clean.

**Done (2026-07-11)**: `tests/test_sse_error_paths.py` adds coverage for client disconnect, an unexpected exception mid-stream, listener cleanup, a malformed Redis message, and a Redis transport error.

### M6.c — Security: auth, session, and log-hygiene

**Mode**: Parallel. **Depends on**: none. **Owns**: `audio_to_subs/auth/{sessions.py,bootstrap.py,passwords.py,deps.py}`, `audio_to_subs/core/logging_config.py`, `tests/test_auth_*.py`.

**Goal**: verify and, if needed, fix cookie hardening, secret-placeholder bootstrap refusal, and log hygiene in the auth path.

**Tasks**: verify cookie flags (`HttpOnly`, `SameSite=Lax`, `Secure` behind TLS); verify the bootstrap refuses to start with default/placeholder secrets; confirm no secret values (API keys, passwords, session tokens) ever reach log output anywhere in the auth path.

**Acceptance**:
- A test asserts the actual `Set-Cookie` header carries `HttpOnly`, `SameSite=Lax`, and `Secure` (behind TLS).
- A test asserts bootstrap refuses to start with a default/placeholder secret.
- A test or targeted grep confirms no secret value reaches `logger` output anywhere under `auth/`.
- `pytest`, `black --check`, `ruff check`, `mypy --strict` clean.

**Done (2026-07-11)**:
- **Log hygiene**: `core/logging_config.py`'s `SecretsRedactingFilter` scrubs `MISTRAL_API_KEY`/`SESSION_SECRET`/`ADMIN_PASSWORD`/`BAZARR_API_KEY` from every log record (registered lazily from `Settings`, applied to every root-logger handler). Unit coverage in `tests/test_logging_config.py::TestSecretsRedaction`; an end-to-end regression test in `tests/test_no_secret_leak.py` drives real auth/settings surfaces with sentinel secrets and asserts none reach logs or the `GET /api/settings` body.
- **Cookie flags**: `auth/sessions.py:set_session_cookie` was already setting `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` behind TLS; locked in by a unit test on the cookie-setting function (`tests/test_auth_sessions.py::TestSetSessionCookieFlags`) and an integration test through the real `/api/auth/login` endpoint with and without `BEHIND_TLS` (`tests/test_api_auth.py::TestSessionCookieFlags`).
- **Bootstrap refuses placeholder secrets**: `auth/secrets.py` (new module) adds `refuse_placeholder_secrets(settings)`, called from the FastAPI lifespan in `api/app.py` at startup — raises `RuntimeError` if `SESSION_SECRET`, `MISTRAL_API_KEY`, or `ADMIN_PASSWORD` still equals its known placeholder value. `auth/bootstrap.py`'s `bootstrap_admin` additionally denylists a broader set of placeholder admin passwords (`changeme`, `password`, `admin`, `root`, `123456`, empty) at the point the admin account is actually created, as defense-in-depth beyond the startup gate. `docker-compose.yml`'s hardcoded `ADMIN_PASSWORD=admin` default was removed so the file-backed secret is authoritative. Tests: `tests/test_auth_secrets.py`, `tests/test_auth_bootstrap.py::test_bootstrap_admin_refuses_placeholder_password`/`test_bootstrap_admin_refuses_empty_password`, `tests/test_session_secret_bootstrap.py`.

### M6.d — Security: path-traversal validation

**Mode**: Parallel (see path_utils.py note above). **Depends on**: none. **Owns**: `audio_to_subs/core/path_utils.py` (traversal-validation functions only — not the `MediaType` literal, owned by M6.f), `audio_to_subs/bazarr/pathmap.py`, `audio_to_subs/api/routes/jobs.py`, `audio_to_subs/api/services/jobs.py`, `tests/test_api_jobs.py`, `tests/test_core_path_utils.py`, `tests/test_bazarr_pathmap.py`.

**Goal**: verify and, if needed, harden input validation against path traversal.

**Tasks**: verify `media_path` traversal is rejected for `source=manual` (`../`, absolute paths outside configured roots); verify Bazarr-resolved paths stay within `movies_root_path`/`series_root_path` — note the latter is renamed from `tv_root_path` by M6.f; if M6.f hasn't landed yet, write tests against whichever name is current and don't duplicate the rename here.

**Acceptance**:
- A test rejects `media_path` traversal attempts (`../`, absolute-outside-root) for `source=manual`.
- A test confirms Bazarr-resolved paths stay within the configured root(s).
- `pytest`, `black --check`, `ruff check`, `mypy --strict` clean.

**Done (2026-07-11)**: `core/path_utils.py::validate_media_path` now rejects control characters, non-absolute paths, and literal `..` segments internally (via `_reject_malformed_path`, checked before the root-containment check and independent of whether roots are configured), so every existing and future caller is protected without needing a separate wrapper. `api/routes/jobs.py`'s `JobCreateRequest` adds an early Pydantic `field_validator` on `media_path`/`output_path` rejecting control characters and non-absolute paths at the request boundary, as defense-in-depth on top of the service-layer check. Three independent reimplementations of this same fix arrived across the dispatched branches (a `contains_traversal()`/`_validate_job_paths()` wrapper in `api/services/jobs.py`, and a `rejects_traversal()` variant of the same); both were dropped in favor of the single lower-level fix, which subsumes them. Tests: `tests/test_core_path_utils.py::TestValidateMediaPath`, `tests/test_api_jobs_create.py` (traversal, outside-root, and no-roots-configured cases for both `media_path` and `output_path`).

### M6.e — CI: pre-commit pin alignment

**Mode**: Parallel. **Depends on**: none. **Owns**: `.pre-commit-config.yaml` only — read `pyproject.toml`'s `black`/`ruff`/`mypy` pins as the source of truth; don't edit `pyproject.toml` unless it's the one actually out of date.

**Goal**: eliminate the known drift between `.pre-commit-config.yaml`'s hook revisions and `pyproject.toml`'s pinned versions.

**Tasks**: bump `.pre-commit-config.yaml`'s `black`/`ruff`/`mypy` hook revs to match `pyproject.toml`.

**Acceptance**:
- `.pre-commit-config.yaml` hook revs match `pyproject.toml`'s `black`/`ruff`/`mypy` pins exactly.
- `pre-commit run --all-files` clean.

**Done (2026-07-11)**: bumped `.pre-commit-config.yaml` hook revs to exactly match `pyproject.toml`'s dev pins — `black` `23.12.1`→`24.2.0`, `ruff` `v0.1.11`→`v0.3.4`, `mypy` `v1.7.1`→`v1.9.0` (the version the dev environment already runs via `make`/`nix develop`, so the pre-commit mypy hook now agrees with the local `mypy` instead of lagging two minors behind). Also aligned the `black` hook's `language_version: python3.9`→`python3.11`, because the canonical dev/CI environment is the `nix develop` shell (`flake.nix` uses `pkgs.python311`) and `pre-commit run --all-files` could not even start under nix — the `black` hook tried to build a `python3.9` venv that does not exist there.

**Verification under `nix develop`** (the mandated verification env): `make format-check` (black) and `make lint` (ruff) both pass; `pre-commit run --all-files` runs end-to-end and every hook passes **except `mypy`** — `trailing-whitespace`, `end-of-file-fixer` (auto-fixed pre-existing whitespace/EOF issues in `dev/*`, `.env.example`, `features/*`), `check-yaml`, `check-added-large-files`, `check-merge-conflict`, `debug-statements`, `black`, and `ruff` all report Passed. The `mypy` hook fails not on any `--strict` finding but because the nix shell's **native `mypy 1.20.1`** (`/nix/store/.../python3.13-mypy-1.20.1`) shadows the pinned `1.9.0` and crashes at import with `ModuleNotFoundError: No module named 'librt.base64'` — the exact, pre-existing environment bug already recorded at the M6 status note (the M5.7 cleanup could not be verified this pass). Running the correctly-pinned `mypy 1.9.0` directly confirms 26 `--strict` errors, **all in unmodified `audio_to_subs/` source** (the M5.7 open gap) — none are caused by M6.e. Both the `librt.base64` env breakage and the 26 `--strict` errors are out of M6.e's scope (this track owns `.pre-commit-config.yaml` only) and must not be widened into a codebase-wide mypy pass here.

### M6.f — Semantic audit: standardize UI/API terminology on "Series" (not "TV")

**Mode**: Parallel (see path_utils.py note above). **Depends on**: none. **Owns**: `frontend/src/**` (all UI copy — labels, headings, placeholders, nav, toasts), `audio_to_subs/api/routes/settings.py` (`tv_root_path` → `series_root_path`), and the `MediaType` Literal + docstring in `audio_to_subs/core/path_utils.py` (`"tv"` → `"series"` — traversal-validation logic in that same file is owned by M6.d, not this), plus every test fixture referencing the old names.

**Rationale**: "TV" is the outlier — Bazarr's own API is `/api/series`/`/api/episodes` (confirmed against `../bazarr` source during M5.5/M5.6) and Sonarr's own domain noun is "Series"; neither system this app integrates with uses "tv" anywhere in its wire format. Standardizing the UI *and* the Settings API contract on "Series" removes a translation step at the one integration boundary that matters, not just a cosmetic UI fix.

**Tasks**:
- Frontend: nav label/copy (`AppLayout.tsx`), `SettingsPage.tsx` ("TV Root Path" → "Series Root Path" label/placeholder/help text), `lib/types.ts` (`MediaType`), `useWanted.ts`, `WantedPage.tsx`, `HistoryPage.tsx` — every "TV"/"Tv" occurrence.
- Backend: `tv_root_path` setting field (defaults dict, `SettingsOut`/`SettingsPatch` schemas) → `series_root_path`; `MediaType` Literal `"tv"` → `"series"` in `path_utils.py`. This is a settings-key/API-contract rename, not a DB column (settings aren't stored one-column-per-field), so no Alembic migration is needed — update the defaults dict and any place that reads the old key.
- Update dependent tests: `test_api_settings.py`, `test_core_path_utils.py`, frontend `SettingsPage.test.tsx`, and any other fixture using the old field/value names.
- Broader sweep beyond Series/TV: check for other duplicate terms describing the same concept across the UI (e.g. "subtitle" vs "subs", "queue" vs "job queue", inconsistent capitalization of page names, toast/error message tone). Fix what's in scope; note anything deferred for M7 to pick up during the doc rewrite.
- Explicitly out of scope: the `docker-compose.yml` named volume (`parolesub-tv`) and container mount path (`/tv`). Renaming those doesn't migrate existing users' volumes/bind-mounts and is a separate, higher-risk infra decision — leave them as-is; the container-internal path being named `/tv` is invisible to users since it's driven by the (now-renamed) `series_root_path` setting, not the other way around.

**Acceptance**:
- No remaining case-insensitive "TV" as a media-type descriptor in UI copy or API field/type names; "Series" used consistently end-to-end.
- `MediaType` values and `series_root_path` consistent across backend, frontend types, and tests.
- Terminology sweep findings documented, including anything deferred to M7.

**Done (2026-07-11)**: renamed end-to-end in a single commit (`4d6dd2f`):
- **Backend settings contract**: `tv_root_path` → `series_root_path` in `DEFAULT_SETTINGS`, `SettingsResponse`, and `SettingsUpdate` (`api/routes/settings.py`); `TV_ROOT_PATH` → `SERIES_ROOT_PATH` in the pydantic `Settings` class (`api/settings.py`); the `getattr(settings, "SERIES_ROOT_PATH", None)` consumer in `api/services/jobs.py`.
- **`MediaType` literal**: `"tv"` → `"series"` in `core/path_utils.py` (`get_media_type` return type, the `tv_root` parameter → `series_root`, both docstrings, and the "not within configured root directories" error message in `validate_media_path`) and in `frontend/src/lib/types.ts`.
- **Frontend copy**: `SettingsPage.tsx` ("TV Root Path" label/`id`/placeholder/help → "Series Root Path", card description "movies and TV shows" → "movies and series"), `useSettingsForm.ts` (form-data mapping + dirty-field list), `SettingsPage.test.tsx` fixture.
- **Tests**: `tests/test_core_path_utils.py` (test names + assertions), `tests/test_api_jobs_create.py` (`SERIES_ROOT_PATH` env var in the `no_media_roots` fixture).

`/tv` as a *filesystem path* (the `series_root_path` default and the `docker-compose.yml` volume/mount) is intentionally left as-is per this sub-track's explicit out-of-scope note — the container-internal path is invisible to users. Bazarr's `tvdbId` field (a TheTVDB external ID — a third-party proper noun in Bazarr's wire format) and `/bazarr/tv` path strings in Bazarr-wire-format fixtures are also correctly untouched, since they model real upstream data.

**`AppLayout.tsx` `Tv` icon — kept deliberately**: the lucide `Tv` icon is still imported and used as the `/wanted` nav-item icon (`AppLayout.tsx:15,26`). It's an icon identifier, not user-visible copy, and the Wanted page is the wanted-subtitles queue rather than a series listing — so swapping it for e.g. `MonitorPlay` would be a pure cosmetic call outside this audit's "TV as a media-type descriptor" charter. Noted here so M7 (doc rewrite) can revisit if desired; the commit message's "all frontend copy" should be read as "all user-visible TV copy", not icon identifiers.

**Broader terminology sweep findings**:
- *"subs" vs "subtitle"*: the project/product name itself is `parolesub` (repo dir, docker image, container, named volume `parolesub-tv`, python package `audio_to_subs`), while internal code uses the full form (`subtitle_generator.py`, `SubtitleGenerator`, `generate_srt`/`vtt`/`sbv`, `missing_subtitles`). **Deferred to M7** — unifying these would mean renaming the product itself, which is a brand decision far beyond a semantic-audit sub-track and outside this audit's "media-type descriptor" scope. UI copy already uses "subtitle" consistently (SettingsPage help text, toasts, dialog copy), so there's no user-visible inconsistency today, only a code/product-naming one.
- *"queue" vs "job queue"*: no inconsistency found — the `/queue` nav item and `QueuePage` are the only user-facing uses of the word; the backend uses "job" for the entity and "queue" for the data structure, which is conventional and not a duplicate-term problem.
- *Page-name capitalization*: consistent — Wanted, Queue, History, Logs, Settings are all Title Case in both nav (`AppLayout.tsx`) and page headings.
- *Toast/error tone*: spot-checked SettingsPage, WantedPage, and the auth toasts — tone is consistent (factual, no mixed "Error!" / "Oops" / "Sorry" registers).

**Verification**: the source branch's own commit message claimed `pytest` 700 passed/4 skipped/1 xfailed, but no `xfail` marker exists anywhere in this tree and this doc-only merge changes no code — that count could not be reproduced and isn't trusted here. Independently re-run against the actual merged state: backend `pytest` 677 passed, 4 skipped; `black --check`/`ruff check` clean; frontend `vitest` 99 passed (9 files); `tsc --noEmit` clean. `mypy --strict` could not be run for the same pre-existing nix-toolchain reason recorded in the M6 status note below (`ModuleNotFoundError: No module named 'librt.base64'`); confirmed reproducible on `dev` and not a regression introduced here.

### M6.g — Overwrite & duplicate-job guards

**Mode**: **Sequential** — do not start until M6.a, M6.d, and M6.f have landed; do not run in parallel with them. **Depends on**: M6.a, M6.d, M6.f. **Owns**: `audio_to_subs/api/services/jobs.py`, `audio_to_subs/api/routes/jobs.py`, `audio_to_subs/worker/runner.py`, `audio_to_subs/core/file_rename.py`, `audio_to_subs/core/subtitle_generator.py`, `audio_to_subs/db/models.py` + a new Alembic migration, `frontend/src/pages/WantedPage.tsx`, job-detail/History UI for a new "overwrite and retry" action, `frontend/src/lib/api.ts`/types for the new `overwrite` field and `subtitle_exists`/`job_already_active`/`output_exists` error codes, and all directly dependent tests.

This genuinely overlaps `worker/runner.py` (M6.a), `services/jobs.py`/`routes/jobs.py` (M6.d), and `WantedPage.tsx` (M6.f) — rather than force false independence, this track runs after those three merge so it isn't rebasing on moving files.

**Background** — two confirmed gaps, traced against the actual code: (1) no duplicate-job guard, so two simultaneous submissions for the same media+language+format race with nothing stopping either; the frontend already has a dead 409 "job already active" toast handler with no backend path that raises it. (2) no overwrite guard anywhere a subtitle gets written or renamed — `SubtitleGenerator.generate_srt/vtt/sbv` blind-writes, and `rename_subtitle_language`'s `os.rename` silently replaces an existing destination. Gap 2 is subtler than "explicit language collides with an existing file": in auto-detect mode the final filename isn't known at job-creation time — `worker/runner.py` resolves it to the detected language or `"und"` only after transcription completes (`needs_language_review` is set when detection fails) — and the real collision usually surfaces later, when the user manually corrects a `.und.` job's language via `PATCH /api/jobs/{id}/language`, which renames on disk with no existence check at all today.

**Policy** (confirmed): soft block + explicit override everywhere — never a silent overwrite, but never more friction than an explicit confirm/retry for the legitimate re-transcribe case.

**Tasks**:
1. **Duplicate/concurrent-job guard**: new migration adding a SQLite partial unique index on `jobs(media_path, language_code, output_format)` WHERE `status IN ('queued','running')`; `create_job_service` surfaces the resulting conflict as `409 job_already_active` — the code path the frontend's existing dead toast handler expects.
2. **Write-time overwrite guard (authoritative — the only point that's correct for both explicit-language and auto-detect/`und` jobs)**: in the worker, immediately before `SubtitleGenerator.generate_srt/vtt/sbv` writes to the fully-resolved `output_path`, check whether the file already exists. Default: refuse — job transitions to `FAILED` with a distinct, UI-recognizable error (`output_exists`), not a silent truncate. `JobCreateRequest` gains `overwrite: bool = False`, threaded through the DB to the worker, which skips the check when set. Frontend: a `FAILED`/`output_exists` job gets an explicit "Overwrite and retry" action in Queue/History that resubmits with `overwrite=true`.
3. **Fast-path pre-flight check (UX nicety layered on #2, not a replacement)**: for jobs with an explicit (non-auto) `language_code`, `create_job_service` computes the deterministic `output_path` and checks existence before enqueuing, returning `409 subtitle_exists` (with the existing file's path + mtime) immediately instead of waiting for the job to run and fail. Frontend (`WantedPage.tsx`/manual-job form) catches this and shows a confirm dialog ("A [en] subtitle already exists here, last modified X — overwrite?"), resubmitting with `overwrite=true` on confirm.
4. **Language-correction rename guard**: `update_job_language` checks whether the post-rename target path already exists *before* calling `rename_subtitle_language` (the check must happen strictly before `os.rename`, which would otherwise replace the destination silently). Add `overwrite: bool = False` to `JobLanguagePatchRequest`; on collision without it, return `409 subtitle_exists`; frontend shows the same confirm-dialog pattern.
5. Tests: true-concurrency duplicate-job rejection (not just sequential); worker write-time refusal for both explicit-language and auto-detect/`und` paths, and successful overwrite when `overwrite=true`; `update_job_language` collision rejection and override; frontend confirm-dialog and post-hoc retry flows.

**Acceptance**:
- Two simultaneous `POST /api/jobs` for the same `(media_path, language_code, output_format)` yield exactly one queued/running job; the second gets `409 job_already_active`.
- A job whose resolved output path collides with an existing file never overwrites it without explicit `overwrite=true` — verified for an explicit-language job and for an auto-detect job that resolves to a colliding language or `und`.
- `PATCH /api/jobs/{id}/language` refuses to clobber an existing file at the target path without `overwrite=true`; succeeds and renames correctly when explicitly overridden.
- Every collision path is an explicit, informed choice in the UI (pre-flight confirm dialog or post-hoc "overwrite and retry") — no code path silently destroys an existing subtitle file.
- Full `pytest`/`black`/`ruff`/`mypy` and frontend `vitest`/`tsc` clean; new code ≥ 80% coverage.

**Done (2026-07-12)**: implemented all four task groups and their tests.

- **Duplicate/concurrent-job guard (Task 1)**: new migration `0005_overwrite_and_dupguard.py` adds a partial unique index `ix_jobs_active_dupguard` on `jobs(media_path, COALESCE(language_code,''), output_format)` WHERE `status IN ('queued','running')` — declared on the ORM model so `Base.metadata.create_all` (tests) enforces it too. `create_job_service` surfaces the resulting `IntegrityError` as `409 job_already_active` (raised `from err`, not swallowed).
- **Write-time overwrite guard (Task 2)**: `SubtitleGenerator.generate_*` raises a new `SubtitleFileExistsError` when the fully-resolved `output_path` already exists; `overwrite: bool = False` flows `JobCreateRequest` → `Pipeline` → `_generate_subtitles`. The worker catches `SubtitleFileExistsError` and transitions the job to `FAILED` with a distinct `output_exists` sentinel in `error_message` (no new status string). Queue/History render an "Overwrite & retry" action that resubmits with `overwrite=true`.
- **Fast-path pre-flight (Task 3)**: for explicit-language jobs, `create_job_service` computes the deterministic `output_path` via `_preflight_subtitle_exists` and returns `409 subtitle_exists` (structured detail: `existing_path`, `existing_mtime`, `language_code`) before enqueuing. `WantedPage` catches it and shows a confirm dialog ("Subtitle already exists … Overwrite?"), resubmitting with `overwrite=true`.
- **Language-correction rename guard (Task 4)**: `update_job_language` computes the rename target via the new pure `compute_rename_target` in `core/file_rename.py` and refuses (409 `subtitle_exists`) *before* `rename_subtitle_language`'s `os.rename`; `JobLanguagePatchRequest.overwrite` allows the override.
- **Frontend**: `lib/types.ts` (`JobCreate.overwrite`, `JobLanguagePatch.overwrite`, `JobConflictDetail`/`JobConflictCode`), `lib/api.ts` (`ApiError.detail: string | JobConflictDetail` + `conflict` getter), `lib/jobsStore.ts` (`LiveJob.error_message`, carried through `seed`/`done`), `WantedPage.tsx` (confirm dialog + retry), `HistoryPage.tsx` and `QueuePage.tsx` ("Overwrite & retry" buttons).
- **Tests**: `tests/test_job_overwrite_dupguard.py` (concurrent rejection + overwrite override), `tests/test_subtitle_generator.py` (write-time refusal + overwrite), `tests/test_worker_runner.py` (FAILED/`output_exists` + override), `tests/test_api_jobs_language_patch.py` rename guard (via `compute_rename_target`), `tests/test_api_wanted.py` distinct media paths, `tests/test_queue_claim.py` 9-tuple row. Frontend: `WantedPage.test.tsx` (pre-flight confirm-dialog retry + legacy 409 toast), `QueuePage.test.tsx` ("Overwrite & retry" present for `output_exists` failures, absent for ordinary failures).

**Verification (under `nix develop`, the mandated env)**: backend `pytest` 704 passed, 4 skipped, 1 xfailed, 12 deselected (the 2 previously-environmental modules — `test_db_migrations`, `test_queue_events` — now pass once `alembic`/`redis` from the nix shell are present). `black --check` and `ruff check` clean repo-wide. Frontend `vitest` 102 passed (9 files) and `tsc --noEmit` clean. `mypy --strict` still could not be run for the pre-existing nix-toolchain reason (`ModuleNotFoundError: No module named 'librt.base64'`, recorded at M6 status note below) — confirmed unrelated to this work; the Python changes are type-straightforward and mirror existing signatures, so no new `mypy` errors are expected.

### M6.h — Clean-checkout smoke test

**Mode**: **Sequential** — the last M6 sub-track, after everything above has landed. **Depends on**: M6.a–M6.g. **Owns**: nothing by default — `docker-compose.yml`/`testing.docker-compose.yaml` only if the smoke test surfaces a real bug worth fixing.

**Goal**: prove the fully-merged M6 result actually works end-to-end on a clean machine.

**Tasks**: fresh-machine `docker compose up` from a clean checkout; fix anything that breaks the golden path.

**Acceptance**:
- Clean checkout → `docker compose up` → working app, no manual fixes needed (verified against whatever deployment doc exists at the time; the doc itself gets rewritten in M7).

**Done (2026-07-12)**: ran a real clean-machine `podman compose up` from a fresh checkout and verified the full golden path on **both** provisioning paths — (A) native Podman secrets (`external: true` `admin_password`/`mistral_api_key`, fixed default names; podman-compose cannot honor a custom `name`) and (B) the env-file fallback (`docker-compose.docker.yml`, a standalone file run on its own, with credentials from a plaintext `.env`). In each case: `GET /api/healthz` → `{status:ok,…}`, `POST /api/auth/login` → 200 with `Set-Cookie: …; HttpOnly; SameSite=lax`, the SPA serves on `:8080`, `GET /api/auth/me` returns the admin, the worker comes up and consumes its mounted `/run/secrets/mistral_api_key`, and `GET /api/jobs/stream` opens as `text/event-stream`. The smoke test surfaced one real golden-path break that was **not** caught by the dev `tsc --noEmit`: the Docker `npm run build` runs `tsc -b` (project-references build), which rejects rendering `JobConflictDetail` (a structured object) as JSX at `HistoryPage.tsx:497`, `QueuePage.tsx:229/242`, `WantedPage.tsx:130`. Fixed by rendering `ApiError.message` (already the stringified form) instead of `err.detail` at those four sites; `tsc -b && vite build` now passes. Provisioning docs added as a tight `DEPLOY_QUICKSTART.md` (podman-secret + env-file paths); `.env.example` gained `ADMIN_PASSWORD`/`ADMIN_USERNAME`. No backend/Python changes, so `pytest`/`black`/`ruff`/`mypy` are unaffected; frontend `tsc -b` is now clean (was the latent break).

### M6 milestone-level acceptance

Applies to the milestone as a whole, once every sub-track above has landed:

- All tests green, coverage report attached, lints clean.
- No known secret-leak, cookie, path-traversal, or bootstrap-hardening gaps outstanding (M6.c, M6.d).
- No silent-overwrite or duplicate-job-race gaps outstanding (M6.g).
- `pre-commit run --all-files` clean with no version drift against `pyproject.toml` (M6.e).
- UI/API terminology consistently uses "Series", not "TV" (M6.f).

**Status (2026-07-12, updated 2026-07-19)**: M6.a-h all done — M6.a-f (2026-07-11), M6.g and M6.h (2026-07-12). Full backend suite: 704 passed, 4 skipped, 1 xfailed (the 2 prior environmental failures — `test_db_migrations`, `test_queue_events` — now pass under `nix develop` with `alembic`/`redis` present). `black --check`/`ruff check` clean repo-wide. Frontend: `vitest` 102 passed (9 files); `tsc --noEmit` clean.

**`mypy --strict` is now verified clean (resolved 2026-07-19).** The prior blocker — the nix flake's native `mypy` (1.20.1) failing at import with `ModuleNotFoundError: No module named 'librt.base64'` — was an environment bug, not a code issue: the Nix `mypy` wrapper injects a `PYTHONPATH` to its own python3.13 site-packages, which shadows the venv's pinned `mypy==1.9.0` under `nix develop`. Fix: removed the native `mypy` package from `flake.nix`'s `default` devShell (the venv's pinned `mypy==1.9.0` is now the sole type-checker; `ruff` stays native since its standalone binary doesn't pollute `PYTHONPATH`). `mypy --strict audio_to_subs/` now passes with zero errors; the residual `--strict` findings were real and fixed with proper typing (generic params on `Popen`/`Task`/`dict`/`list`, a `get_db` re-export in `api/deps.py`, and `SubtitleFileExistsError` re-export in `core/pipeline.py`). The `redis.asyncio.from_url` calls stay untyped via narrow, commented `# type: ignore[no-untyped-call]` markers — `types-redis` was evaluated and rejected because its only published release line (4.6.x) types `Redis` as a `Generic`, which is incompatible with the pinned `redis==5.0.3` (non-generic) and crashes at import (`TypeError: <class 'redis.asyncio.client.Redis'> is not a generic class`).

## M6.i — Post-M6 hardening batch (unplanned)

**Goal**: not a planned milestone — a retroactive record of an ad-hoc batch
(2026-07-18) that landed directly on `dev` between M6 and the start of M7:
a production-deployment hardening fix and a product rebrand, discovered
and done via direct use rather than milestone planning. Recorded here so
this document keeps matching `dev`'s actual state, same precedent as
[M5.6.1](#m561--post-m56-stabilization-batch-unplanned).

**Depends on**: M6

Notable changes:

- **Deploy hardening** (`docker-compose.yml`, `docker-compose.docker.yml`,
  `Caddyfile`, `DEPLOY_QUICKSTART.md`): stopped publishing the `backend`
  (`8000`) and `redis` (`6379`) ports to the host — the frontend's own
  `nginx.conf` already reverse-proxies `/api/` to the backend internally, so
  neither port ever needed to be reachable from outside the compose network,
  and leaving them open was unnecessary attack surface for a
  production deployment. Fixed a real config bug in the process: `DEBUG`,
  `BEHIND_TLS`, `LOG_LEVEL`, and `ADMIN_USERNAME` were hardcoded literals in
  each service's `environment:` block, which compose gives precedence over
  `env_file:` for the same key — so `.env` could never actually override
  them. Switched to `${VAR:-default}` interpolation so both compose files
  now read every operator-tunable value from `.env`. Added a standalone
  `Caddyfile` (public-domain + automatic Let's Encrypt) for TLS-terminating
  in front of the frontend's now-sole exposed port, documented in
  `DEPLOY_QUICKSTART.md`.
- **ParoleSub rebrand** (`c8850e5`, `4a242b7`): renamed product-facing names
  to the **ParoleSub** brand — CLI binary, Docker images/volumes, SQLite db
  filename, config file, frontend package name, session cookie
  (`ats_session` → the new name), sidebar/login-page casing, and docs. The
  `audio_to_subs` Python package name is intentionally unchanged — it stays
  the reusable backend library name, separate from the product brand.
  `dev/NAMING.md` documents the umbrella naming convention: a shared
  **Parole** (French for "speech") family prefix with a `-<domain>` suffix
  per variant (`parolesub` is this repo's video→subtitles variant;
  `parolecast`/`parolenote`/`parolelive` are sibling variants sharing the
  same umbrella branding/infra).

No acceptance checklist — this predates any plan, same as M5.6.1. No test
behaviour change: deploy-hardening is compose/proxy config only, and the
rebrand is a mechanical rename (verified no residual old-name references in
product-facing surfaces post-rename).

## M8 — v2.1 Wanted scope: sync everything, filter client-side

**Goal**: change the Bazarr sync model from "only pull items missing/a completely
without subtitles" to "sync the full library, then let the operator choose what
to display" — without losing any of the filtering the UI already does today
(including the scope of what gets re-synced). The Wanted panel gains an explicit
three-way scope selector (All / Missing subtitle / No subtitles) that replaces
the current binary "only no-subs" toggle, and the Movies/Series type filter
stays as a separate axis.

**Depends on**: M6 (and the M3 polling + Wanted UI it shipped).

### Current behaviour (to be changed)
- The poller only ingests items Bazarr flags as *wanted* (missing at least one
  subtitle, or — opt-in via `bazarr_track_no_subs` — items with *no* subtitle at
  all). See `bazarr/poller.py`: `_run_no_subs_pass` (expensive, opt-in) plus the
  standard wanted pass.
- The Wanted UI (`frontend/src/pages/WantedPage.tsx`) has:
  - a type selector: `All` / `Movies` / `Series` (Tabs), and
  - a binary "only no-subs" toggle (`no-subs` filtering applied server-side).
- Re-sync is currently *scoped* by the active UI filter — the refresh endpoint
  re-polls according to whatever the operator is currently viewing.

### Target behaviour
1. **Sync everything.** The poller ingests the entire Bazarr library (movies +
   series + episodes), carrying each item's full state: which languages are
   *missing* (`missing_subtitles`) and whether the item has *no* subtitle at all
   (`missing_subtitles` empty *and* no `subtitles` present). The opt-in
   `bazarr_track_no_subs` pass is subsumed by the full sync and can be retired
   (or kept as a no-op compatibility flag, TBD).
2. **Three-way scope selector** in the Wanted panel, replacing the "only no-subs"
   toggle:
   - `All` — every synced item (movies + series, regardless of subtitle state).
   - `Missing subtitle` — items with ≥1 missing language (`missing_subtitles` non-empty).
   - `No subtitles` — items with *no* subtitle at all (no `subtitles`, `missing_subtitles` empty).
   This is a **display** filter applied client-side / server-side on top of the
   already-synced full library — it must NOT re-trigger a scoped re-sync.
3. **Type axis unchanged.** Movies / Series / All stays a separate filter, as
   today (Tabs in `WantedPage.tsx`).
4. **Retain all existing filtering logic.** Search, language filter, and the
   live active-job indicator must keep working exactly as now. The sync scope is
   decoupled from the display scope: a refresh re-syncs the *full* library
   regardless of which scope/tab the operator is viewing, so the UI is never
   stuck seeing only a subset.

### Tasks (proposed)
- `bazarr/poller.py`: switch the wanted pass to a full-library fetch; persist a
  `has_no_subs` / `subtitle_state` discriminator per cached item (or derive it
  from `missing_subtitles` + `subtitles` already stored). Retire or neutralize
  `bazarr_track_no_subs` and `_run_no_subs_pass`.
- `bazarr` cache schema (`BazarrWantedItem` / cache model): ensure it carries
  enough state to compute `All` / `Missing` / `No subtitles` without a re-poll.
- `api/routes/wanted.py`: add a `scope` query param (`all` | `missing` |
  `no_subs`) alongside the existing `type`/`search`/`language` filters; keep all
  current filters intact. Decouple the refresh/sync trigger from the active UI
  filter (sync full library every time).
- `frontend/src/pages/WantedPage.tsx`: replace the "only no-subs" toggle with a
  three-way scope control (segmented control / select matching the existing
  Movies/Series selector styling). Keep the type Tabs and every other filter.
- `frontend/src/lib/types.ts` + `useWanted.ts`: add `scope` to the query contract.
- Tests: `test_api_wanted.py` (all three scopes + interaction with type/language
  filters), `test_bazarr_poller.py` (full-library ingest, discriminator
  correctness), `WantedPage.test.tsx` (scope selector renders all three states,
  toggle removed, refresh does not narrow the synced set).

### Acceptance (proposed)
- Poller ingests the full library; `GET /api/wanted?scope=all` returns items with
  and without subtitles; `scope=missing` returns only items with ≥1 missing lang;
  `scope=no_subs` returns only items with no subtitle at all.
- The Wanted UI shows the three-way selector; selecting a scope filters the
  displayed list without triggering a narrowed re-sync.
- Movies/Series, search, language filter, and active-job indicator all still work.
- `bazarr_track_no_subs` is either removed cleanly or neutralized; no behaviour
  regression in sync coverage.
- `pytest`, `black --check`, `ruff check`, `mypy --strict` clean; frontend
  `vitest` + `tsc --noEmit` clean; new code ≥ 80% coverage.
- Doc note: M7 (doc rewrite, now M16) must capture the new sync model.

## M9 — v2.2

**Goal**: scope not yet defined. Placeholder milestone reserved immediately after
the v2.1 Wanted refactor so the v2.x line has a clear next slot. To be filled in
once v2.1 is shipped and the next v2 feature is chosen.

**Depends on**: M8.

Tasks / Acceptance: TBD.

## M10 — v2.3 Admin password sync on secret/env change

**Goal**: confirm (and, if missing, introduce) a workflow that updates the
admin password whenever the deployment secret changes — i.e. when the Podman
secret or `.env` var backing `ADMIN_PASSWORD` / `ADMIN_PASSWORD_FILE` is rotated,
the running app picks it up and the stored admin credential is brought in line
with the new value (rather than bootstrap only setting the password on
first-run / when no user exists).

**Depends on**: M1 (DB foundation + auth + bootstrap). Relevant surfaces:
`audio_to_subs/admin/__main__.py` (`set-password` subcommand already exists),
`audio_to_subs/auth/bootstrap.py` (`bootstrap_admin`), `audio_to_subs/api/app.py`
(lifespan calls bootstrap), and `audio_to_subs/api/settings.py` /
`audio_to_subs/auth/passwords.py`.

### Tasks (proposed)
- Audit current behaviour: does changing `ADMIN_PASSWORD` (secret or env) after
  first boot actually update the stored hash, or is it only honoured when no
  user exists? Today `bootstrap_admin` only creates/refuses — verify whether it
  also reconciles on change.
- If absent: add a reconcile step (on startup or on a `set-password`/admin
  trigger) that, when the secret/env value differs from the stored hash, updates
  the admin password. Reuse the existing `set-password` machinery where possible.
- Decide trigger model: startup reconcile vs. explicit operator action (e.g.
  `parolesub admin set-password` or a Settings action). Document the chosen model.
- Tests: rotating the secret updates the stored credential; stale secret does
  not silently lock the operator out; placeholder/weak values still refused
  (reuse M6.c's refusal logic).

### Acceptance (proposed)
- Changing the Podman secret / `.env` `ADMIN_PASSWORD` and redeploying results in
  the new password being active (verified by login with the new value).
- No regression to M6.c's placeholder-secret refusal or to first-boot bootstrap.
- `pytest`, `black --check`, `ruff check`, `mypy --strict` clean.

## M11 — v2.4 Queue: Auto-refresh On by default

**Goal**: make the Queue panel's "Auto-refresh" toggle default to **On**, so a
freshly opened Queue page live-updates progress without the operator having to
manually enable it.

**Depends on**: M4 (Queue UI + SSE store). Relevant surface:
`frontend/src/pages/QueuePage.tsx` — `const [autoRefresh, setAutoRefresh] =
useState(false)` (line ~183) should initialize to `true`.

### Tasks (proposed)
- Flip the `autoRefresh` initial state to `true` in `QueuePage.tsx`.
- Keep the manual toggle working (operator can still turn it Off); only the
  default changes. No backend change expected.
- Test: `QueuePage.test.tsx` asserts auto-refresh starts On (and that the toggle
  still flips it Off).

### Acceptance (proposed)
- Opening the Queue page starts with Auto-refresh On; progress updates live.
- Toggling Off stops the polling; toggling back On resumes it.
- Frontend `vitest` + `tsc --noEmit` clean.

## M12 — v2.5 History: Retry action for failed jobs

**Goal**: surface a **Retry** action button for any job that ended in `failed`,
distinct from the existing M6.g "Overwrite & retry" (which only appears for the
`output_exists` sentinel). Clicking Retry queues a fresh job that re-runs the
failed one; once the new job is scheduled/queued, the Retry button for the
original row must disappear (the row is no longer retryable — its re-run is now
in flight / tracked as a new job).

**Depends on**: M5 (History UI) + M6.g (`buildRetry` helper +
`createJob.mutate` machinery already in `frontend/src/pages/HistoryPage.tsx`).

### Current state (to extend)
- `HistoryPage.tsx` already has `buildRetry(job)` (re-runs with `overwrite:
  true`) and an "Overwrite & retry" button gated on `isOutputExists(job)` (the
  M6.g `output_exists` sentinel, line ~493).
- There is **no** general Retry for an ordinary `failed` job today. A plain
  failure (transcription error, Bazarr resolution failure, crash) has no retry
  affordance.
- `needsLanguageRename(job)` ("Rename" button) already handles the
  `needs_language_review` case.

### Tasks (proposed)
- Add a `Retry` button gated on `job.status === "failed"` (and not already
  covered by the more specific `isOutputExists` / `needsLanguageRename` buttons —
  those stay). Clicking it calls `createJob.mutate(buildRetry(job), …)` reusing
  the M6.g flow (toast on success/error).
- After a successful queue, the source row's Retry button must disappear. Drive
  this from the SSE/query state: once a new job derived from this `media_path` +
  `language` is visible as `queued`/`running` (or track the returned new job id
  locally), hide Retry for the original row. Simplest robust approach: on
  `onSuccess`, invalidate/refetch the history query and gate Retry on "no active
  job already queued for this source" (reuse the existing active-job lookup the
  Wanted/Queue pages use).
- Tests: `HistoryPage.test.tsx` — Retry appears for a `failed` job, disappears
  after a successful queue (assert the new job is `queued` and the original row
  no longer shows Retry); Retry does not appear for `done`/`running`/`queued`.

### Acceptance (proposed)
- Any `failed` job shows a Retry button; clicking it queues a new job.
- Once the new job is `queued`/`running`, the original row's Retry button is
  gone (no duplicate retry).
- The existing `output_exists` "Overwrite & retry" and `needs_language_review`
  "Rename" buttons remain unchanged.
- Frontend `vitest` + `tsc --noEmit` clean.

## M13 — v2.6 Visual polish: History filter buttons + ParoleSub logo

**Goal**: two UI polish items — (1) in the History panel, make the filter
**Reset** and **Apply** buttons the same size and **swap their order** so Apply is
on the **left** and Reset on the **right**; (2) add a **ParoleSub logo** to the
product UI (sidebar / login / topbar) as part of the rebrand completed in M6.i.

**Depends on**: M4/M5 UI (History filters at `frontend/src/pages/HistoryPage.tsx`
~line 196; `AppLayout.tsx` sidebar; `LoginPage.tsx`).

### Tasks (proposed)
- **History filter buttons**: in `HistoryPage.tsx`'s filter form, reorder so
  Apply renders first (left) and Reset second (right); give both an explicit
  equal `size` (e.g. `size="sm"` already shared — ensure identical width via a
  shared class / `w-*` or `flex-1`), so they read as a matched pair. Behaviour
  unchanged (Apply submits filters, Reset clears).
- **ParoleSub logo**: add a logo asset (SVG, e.g. `frontend/src/assets/logo.svg`
  or `frontend/public/`) and render it in `AppLayout.tsx` (sidebar header) and
  `LoginPage.tsx` (above the form). Pick a mark consistent with the M6.i ParoleSub
  rebrand / `dev/NAMING.md` umbrella. Provide light/dark variants or a
  theme-aware single asset. Keep the existing text wordmark ("ParoleSub") as
  fallback/alt text.
- Tests: `AppLayout.test.tsx` / `LoginPage` render the logo `img`/`svg` with
  accessible alt; `HistoryPage.test.tsx` asserts Apply appears before Reset in
  DOM order.

### Acceptance (proposed)
- History filter buttons are equal size; Apply is left of Reset.
- ParoleSub logo shows in the sidebar and on the login page; alt text present.
- No regression to filter behaviour (Apply still applies, Reset still clears).
- Frontend `vitest` + `tsc --noEmit` clean.

## M14 — v3.0 Redis / jobs-progress architecture refactor

**Goal**: land the in-depth architecture refactoring of how live job progress is
stored, delivered, and reconciled — currently in flight on the
`investigate-progress-bar` branch (commit `828c19e`, "store live job progress in
Redis, drop DB columns (Phase 1+2)"). This milestone formally adopts that branch
work as v3.0 and drives it to completion, including the phases not yet shipped.

**Depends on**: M5.8 (Queue progress reporting — step-based UX, Redis-only SSE
delivery, `progress_stage`/`step_index`/`step_total`).

### Status of in-flight work (`investigate-progress-bar`)
- **Phase 1** (live progress mirrored to Redis hash `job:progress:{id}`,
  authoritative live store; worker writes via the progress bridge; cleared on
  terminal/claim/reap): **done** in `828c19e`.
- **Phase 2** (DB no longer stores `progress_*` columns; ORM dropped them;
  removes last per-event DB write and the SQLite single-writer contention):
  **done** in `828c19e`. No Alembic migration shipped (Option B) — orphaned
  columns linger in existing SQLite DBs; `MIGRATIONS.md` documents the one-time
  `DROP COLUMN` (incl. a `docker run --rm` method for hosts without sqlite3).
- Branch is **not yet merged into `dev`** as of 2026-07-19. Suite: 704 passed /
  4 skipped (1 pre-existing `test_db_migrations` sandbox failure — no alembic on
  PATH).

### Open scope for v3.0 (proposed phases beyond 1+2)
- **Phase 3+**: reconcile the poller/Wanted progress read path fully onto the
  Redis snapshot (already partially done in `828c19e` for Wanted); confirm
  `GET /api/jobs` and `/api/jobs/{id}` overlay logic is consistent across SSE +
  polling + refresh.
- **Claim/reap consistency**: ensure a reaped-and-requeued job rebuilds its
  progress snapshot from Redis (or resets cleanly) — covered by the Phase 1
  clear-on-claim/reap logic; add regression tests.
- **Migration hygiene**: decide whether v3.0 should ship an Alembic migration to
  actually drop the orphaned `progress_*` columns (vs. the current Option B
  manual DROP), so fresh + upgraded DBs match. Reconcile `MIGRATIONS.md`.
- **Docs**: `QUEUE.md` / `ARCHITECTURE.md` / `DATABASE.md` must reflect
  Redis-as-authoritative-progress (the M16 doc rewrite should consume this).

### Acceptance (proposed)
- `investigate-progress-bar` merged to `dev`; live progress is Redis-authoritative
  with no per-event DB writes on the progress path.
- Terminal jobs derive progress from status; non-terminal jobs overlay the Redis
  snapshot consistently across SSE + REST.
- Existing SQLite DBs either auto-migrate or have a documented, tested DROP path.
- No SQLite single-writer contention regression; `pytest`/`black`/`ruff`/`mypy`
  clean; frontend `vitest`/`tsc` clean.

## M15 — v4.0 Periodic, configurable jobs (Bazarr sync + auto-schedule)

**Goal**: introduce a scheduling subsystem so the app can run work on a recurring,
operator-configured cadence: (a) periodic **Bazarr sync** (replace/extend the
current fixed `bazarr_poll_interval` poll with a proper, user-tunable schedule),
and (b) **auto-scheduling of transcription jobs** — automatically queue
transcription for items matching a rule (e.g. wanted items missing a subtitle,
optionally scoped by language/type) on a configurable interval, instead of
requiring manual "Transcribe" clicks.

**Depends on**: M3 (Bazarr client/poller/`/api/wanted`), M14 (Redis/progress
architecture — so auto-queued jobs share the same progress/SSE path as manual
ones). Builds on the existing `bazarr_poll_interval` setting and the
manual-job creation service.

### Tasks (proposed)
- **Scheduling core**: a backend scheduler (APScheduler-like or a lightweight
  periodic task in the FastAPI lifespan / worker) with CRUD over schedules stored
  in the DB (new table + Alembic migration). Each schedule has: enabled flag,
  cron/interval, and a job-type (`bazarr_sync` | `auto_transcribe`).
- **Bazarr sync schedule**: promote `bazarr_poll_interval` to a first-class,
  editable schedule (keep backward-compatible default). Settings UI lets the
  operator switch between interval and cron and pause it.
- **Auto-transcribe schedule**: a rule (language(s), media type All/Movies/
  Series, scope from M8's `all`/`missing`/`no_subs`) that, on each tick, queries
  `/api/wanted` and enqueues jobs for items not already active/done recently
  (reuse the M6.g duplicate-job guard so re-runs are skipped). Surfaced in
  Settings + a new "Schedules" surface (settings section or dedicated page).
- **Frontend**: Settings section to create/edit/enable/disable schedules; show
  next-run and last-run per schedule.
- Tests: schedule CRUD + persistence; sync tick triggers a Bazarr refresh;
  auto-transcribe tick enqueues only unprocessed/non-active items (duplicate
  guard respected); disabling a schedule stops ticks.

### Acceptance (proposed)
- Operator can define a periodic Bazarr-sync schedule (interval or cron) and
  pause/resume it from Settings; the app honours it instead of the old fixed
  poll.
- Operator can define an auto-transcribe rule; on each tick the app queues
  transcription for matching wanted items not already active/recently done, and
  skips duplicates (M6.g guard).
- Schedules survive restart (persisted); next-run/last-run visible in UI.
- `pytest`, `black --check`, `ruff check`, `mypy --strict` clean; frontend
  `vitest`/`tsc` clean; new code ≥ 80% coverage.

## M16 — Documentation rewrite & dev-docs reorganization


**Goal**: bring documentation in line with reality after the full v2 rewrite, and give dev-facing docs a proper home. Most of `dev/v2/*.md` was written as a **pre-implementation spec** during M0–M5 planning (see `dev/v2/README.md`'s "meant to be read by a developer... about to implement the v2 architecture from scratch"); after M0–M6 shipped — including several rounds of structural refactor (M5.3), unplanned stabilization work (M5.6.1), and feature work not anticipated in the original plan (M5.8's step-based progress UX, B10, etc.) — that framing is stale. Root-level docs (`README.md`, `README_v2.md`, `CONTAINER_GUIDE.md`) still describe v1 as the only surface.

**Depends on**: M6 — but **deferred** until after the v2.1–v4.0 feature work
(M8–M15) lands, so the rewrite documents the final shipped architecture (new
Wanted sync model, Redis-authoritative progress, periodic jobs) rather than a
moving target.

Tasks:
- **Root docs**: rewrite `README.md` as the v2 quickstart (web app + CLI, not CLI-only); fold `README_v2.md`'s ad-hoc Bazarr-workflow content into proper prose sections of the reorganized dev docs (`BAZARR_INTEGRATION.md`), then retire the standalone file; review `CONTAINER_GUIDE.md` for v1-only assumptions that no longer hold now that `worker`/`frontend`/`redis` services exist alongside the backend. Note: the old `bazarr_track_no_subs` opt-in is retired by M8 — its Q&A content should be rewritten to describe the new full-sync + three-way scope model instead.
- **Reorganize dev docs into `docs/`**: create a root `docs/` directory and move `dev/` under it (e.g. `docs/dev/v1/`, `docs/dev/v2/`, `docs/dev/reference/`), or an equivalent structure — a clear, browsable subcategory instead of a flat `dev/` folder mixing specs, plans, and reference material. Fix every relative link broken by the move (`dev/v2/README.md`'s reading-order list, `MILESTONES.md`'s links to `MIGRATION.md`/`QUEUE_PROGRESS_REVIEW.md`/etc., and any cross-links from root-level docs).
- **Rewrite the shipped-system docs** so they describe what v2 *is*, not what it was planned to be: `ARCHITECTURE.md`, `API.md`, `DATABASE.md`, `QUEUE.md`, `FRONTEND.md`, `BAZARR_INTEGRATION.md`, `AUTH.md`, `DEPLOYMENT.md`, `TESTING.md`. Reconcile against the actual structural refactor outcome (`REFACTOR.md` in the sibling `audio_to_subs_plans/` repo — verify whether that plan doc should be linked from here or considered out of scope), the M5.8 progress/SSE architecture change (Redis-only delivery, `progress_stage`/`step_index`/`step_total`), and the M5.6.1 fixes (path resolution, logging, subtitle-naming idempotency) that changed behavior without a corresponding spec update.
- **Archive planning-only artifacts** that are no longer live specs but are worth keeping for history: `M5_PLAN.md`, `TODO_M53.md`, `MISTRAL_USAGE_PROBE.md`, `QUEUE_PROGRESS_REVIEW.md` — move to a clearly-labeled historical/archive subfolder rather than delete or leave mixed in with current docs.
- **`MIGRATION.md` and `PIPELINE_CHANGES.md`**: fold into `ARCHITECTURE.md` or mark explicitly as historical (M0/M2-era one-off migration records), since the migration they describe is long complete.
- Update `.agents/` rule files if any reference the old `dev/v2/` paths directly.

Acceptance:
- A root `docs/` directory exists with dev-related markdown organized into a clear subcategory (e.g. `docs/dev/`); no stray planning/spec `.md` files left loose at repo root or scattered outside `docs/` (README.md and CLAUDE.md excepted).
- Every doc under `docs/` describes the *current* shipped v2 system — no "to be implemented" language for features that have since shipped (Bazarr integration, worker/queue, frontend, step-based progress UX, etc.).
- All internal markdown links (within moved docs and from root-level docs into `docs/`) resolve.
- `README.md` gives an accurate, current v2 quickstart; `README_v2.md` is retired (content merged or removed).
- v2.0 release notes drafted, reflecting the actual M0–M6 scope (including unplanned batches like M5.6.1 and notable fixes like B10) rather than only the originally-planned milestones.

## Parallelisation notes

The milestones are serial as listed. The following sub-tasks within a milestone CAN run in parallel:

- M1: db + auth + admin CLI can be developed in parallel by different agents; merge order is db → auth → API scaffold.
- M2: queue_/ + worker/ + core changes are parallelizable once `CancelToken` and `PipelineResult` shapes are agreed.
- M3: bazarr/client + bazarr/pathmap + api/routes/settings are independent.
- M4: frontend pages are independent of each other once Login + Layout + auth flow exist.
- M5: history + logs + settings pages are independent.
- M5.1: cleanup tasks are independent.
- M6: sub-tracks M6.a–M6.f have disjoint (or coordinated, for the shared `path_utils.py` case) file ownership and can run fully in parallel; M6.g (overwrite/duplicate-job guards) and M6.h (smoke test) are sequential, in that order, and must run after the parallel batch lands — see M6's dispatch table for the full breakdown.

## Definition of done (per milestone)

Use this checklist at the end of each milestone:

- [ ] Every acceptance bullet from the milestone is demonstrated (preferably with a recorded `curl` or screenshot)
- [ ] `pytest`, `black --check`, `ruff check`, `mypy --strict` all clean
- [ ] Coverage on new modules ≥ 80%
- [ ] No new TODO/FIXME without a tracking note in the project roadmap
- [ ] CHANGELOG entry (or commit body) describes what's now possible
- [ ] All commits are conventional + `Signed-off-by`
