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
| M5.6 — M5.5 code-review follow-up (schema tightening, dead-field removal, error UX) | ⏳ Not Started | - | Depends on M5.5 |
| M6 — Polish + docs | ⏳ Not Started | - | Depends on M5.6 |

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

**Authoritative plan**: [`../../../audio_to_subs_plans/REFACTOR.md`](../../../audio_to_subs_plans/REFACTOR.md)
(sibling directory to this repo). That document is the source of truth for
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
- M5.1: cleanup tasks are independent.

## Definition of done (per milestone)

Use this checklist at the end of each milestone:

- [ ] Every acceptance bullet from the milestone is demonstrated (preferably with a recorded `curl` or screenshot)
- [ ] `pytest`, `black --check`, `ruff check`, `mypy --strict` all clean
- [ ] Coverage on new modules ≥ 80%
- [ ] No new TODO/FIXME without a tracking note in the project roadmap
- [ ] CHANGELOG entry (or commit body) describes what's now possible
- [ ] All commits are conventional + `Signed-off-by`
