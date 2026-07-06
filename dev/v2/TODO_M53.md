# M5.3 — Refactor Todo List

> **Branch**: `dev-refactor`
> **Plan**: [`REFACTOR_zaiglm52.md`](REFACTOR_zaiglm52.md)
> **Last updated**: 2026-07-06

## Progress

| Increment | Status | Priority |
|-----------|--------|----------|
| A1 — BDD suite repair | ✅ Done | High |
| A2 — Decouple refactor-hostile tests | ⏳ Pending | High |
| A3 — Fix vacuous/broken tests + add missing coverage | ⏳ Pending | High |
| B1–B6 — P0 correctness (core) | ⏳ Pending | High |
| B7–B25 — P0 correctness (API/auth/worker/queue) | ⏳ Pending | High |
| C1–C11 — P0 security hardening | ⏳ Pending | High |
| D1–D18 — P1 architecture | ⏳ Pending | Medium |
| E — P2/P3 cleanup | ⏳ Pending | Low |
| G1 — Update TESTING.md | ⏳ Pending | Low |
| G2 — Add M5.3 section to MILESTONES.md | ✅ Done | Low |

## Todo

- [x] **A1** — BDD suite repair *(commit `e930ade`)*
- [ ] **A2** — Decouple refactor-hostile tests
- [ ] **A3** — Fix vacuous/broken tests + add missing coverage
- [ ] **B1** — `_last_response` never set → `mistral_usage` always None
- [ ] **B2** — `split_audio` swallows `Cancelled` into `AudioSplitterError`
- [ ] **B3** — Batch-mode progress callback references undefined `progress` (NameError)
- [ ] **B4** — `--model` option silently ignored in batch mode
- [ ] **B5** — Temp audio filename collides across batch jobs with same stem
- [ ] **B6** — Subtitle files written without explicit UTF-8 encoding
- [ ] **B7** — `_publish` never awaits `redis.publish` (pub/sub dead)
- [ ] **B8** — Reaper requeues every running job (timestamp format mismatch)
- [ ] **B9** — Stage-transition job logs never written
- [ ] **B10** — `has_any_subs` semantic inverted in poller
- [ ] **B11** — `output_path` never validated (arbitrary file write)
- [ ] **B12** — `_get_path_map` reads `.value_json` off scalar string (AttributeError)
- [ ] **B13** — `list_jobs` returns `total = len(jobs)` (page size, not total)
- [ ] **B14** — Per-job SSE deletes shared queue on first disconnect
- [ ] **B15** — `get_wanted_item` reads `job.status.value` off plain string (AttributeError)
- [ ] **B16** — Worker ignores `mistral_model`/cost rates from DB settings
- [ ] **B17** — `Job.id == job_id` (UUID) vs `String(36)` in stream.py
- [ ] **B18** — Engine/sessionmaker cache by first DSN only; admin CLI wrong DB
- [ ] **B19** — Sliding session renewal hardcodes `secure=False`
- [ ] **B20** — Blocking `subprocess.run` inside async lifespan
- [ ] **B21** — `get_session_manager` singleton first-call-wins; secret ignored
- [ ] **B22** — `list_wanted` uses `func.json_contains` (nonexistent in SQLite)
- [ ] **B23** — `update_settings` non-atomic read-modify-write
- [ ] **B24** — `list_jobs` status-counts query ignores filters + unindexed GROUP BY
- [ ] **B25** — `process_batch` raises on first failure (no continue-on-error)
- [ ] **C1** — Path-traversal via `startswith` in `validate_media_path`
- [ ] **C2** — `abspath` doesn't resolve symlinks → root escape
- [ ] **C3** — No auth on jobs/settings/wanted/history/logs/stream routes
- [ ] **C4** — No `User` role/`is_active`; no RBAC
- [ ] **C5** — CORS `allow_origins=['*']` with `allow_credentials=True`
- [ ] **C6** — `GET /api/settings/{key}` exposes `bazarr_api_key`
- [ ] **C7** — Unauthenticated SSRF via `bazarr_url` in PATCH settings
- [ ] **C8** — `healthz` leaks DB error details
- [ ] **C9** — `SESSION_SECRET` placeholder accepted; brittle startup ordering
- [ ] **C10** — Real Mistral API key loaded from hardcoded dev path in tests
- [ ] **C11** — Weak `admin123` password in autouse test fixture
- [ ] **D1** — No retry/circuit-breaker around Mistral API calls
- [ ] **D2** — No timeout on Mistral API / FFmpeg subprocess
- [ ] **D3** — Pointless chunked read loads entire audio into memory
- [ ] **D4** — `check_ffmpeg_available` runs on every extraction
- [ ] **D5** — Hardcoded split thresholds should be configurable
- [ ] **D6** — `get_audio_duration` called twice per video
- [ ] **D7** — Monkey-patching `queue_.events` from `stream.py`
- [ ] **D8** — In-process SSE queues process-local; multi-worker gets no events
- [ ] **D9** — N+1 query in `list_wanted` for active job status
- [ ] **D10** — `_calculate_stats` loads all jobs into memory
- [ ] **D11** — `update_settings` performs N separate SELECTs
- [ ] **D12** — `_seed_default_settings` runs on every GET /api/settings
- [ ] **D13** — Raw SQL `UPDATE` bypasses ORM and `onupdate`
- [ ] **D14** — `_reaper_task` stored as module global, not `app.state`
- [ ] **D15** — Worker outer loop dead; job stuck if `run_job` setup raises
- [ ] **D16** — Bootstrap-then-commit double commit
- [ ] **D17** — `test-bazarr-connection` error mapping by string compare
- [ ] **D18** — BDD steps mock entire Pipeline interior
- [ ] **E** — P2/P3 cleanup (core + API + tests)
- [ ] **G1** — Update TESTING.md
- [x] **G2** — Add M5.3 section to MILESTONES.md
