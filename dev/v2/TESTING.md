# v2 — Testing strategy

This document describes the testing infrastructure as it actually exists in
the codebase. If you're adding tests, start here rather than re-deriving
conventions from scratch.

Same base conventions as v1:

- One `tests/test_<module>.py` per source module, mirroring the package tree
  (`audio_to_subs/core/`, `audio_to_subs/api/`, `audio_to_subs/auth/`,
  `audio_to_subs/bazarr/`, `audio_to_subs/queue_/`, `audio_to_subs/worker/`,
  `audio_to_subs/db/`, `audio_to_subs/admin/`).
- Unit tests use `unittest.mock`-style `@patch`; integration tests are marked
  `@pytest.mark.integration` and skip without `MISTRAL_API_KEY`.
- `pytest --cov` with the ≥80% gate on new code (coverage config lives in
  `pyproject.toml` under `[tool.coverage.*]`).
- `black` (line 88) + `ruff` + `mypy --strict` clean.

## Dev dependencies (`[project.optional-dependencies].dev` in `pyproject.toml`)

| Package | Pin | Purpose |
|---|---|---|
| `pytest` | `==8.0.0` | Test runner |
| `pytest-bdd` | `==7.0.0` | Collects `features/*.feature` as part of the normal test run (see below) |
| `pytest-cov` | `==4.1.0` | Coverage (`--cov=audio_to_subs`, term/html/xml reports) |
| `pytest-asyncio` | `==0.23.7` | `async def` tests; `asyncio_mode = "auto"` in `pyproject.toml`, so `async def test_*` needs no `@pytest.mark.asyncio` marker (but the existing tests use the explicit marker anyway — harmless under `auto` mode) |
| `freezegun` | `==1.5.0` | Deterministic time control — freeze/advance the clock instead of `time.sleep` |
| `respx` | `==0.22.0` | httpx mocking (Bazarr client tests) |
| `genbadge[coverage]` | `==1.1.3` | Coverage badge generation in CI (main branch only) |
| `black`, `ruff`, `mypy` | pinned | Formatting / lint / type-check gates |

`fakeredis` is used in test code (`tests/test_queue_events.py` imports
`fakeredis.aioredis`) but is **not** currently declared as an explicit `dev`
extra or in `requirements-dev.txt` — it rides in transitively today. Treat
this as tech debt: if you touch dependency pins, add it explicitly.

## Test layout (`tests/`)

```
tests/
  conftest.py                      # shared fixtures — see below
  test_audio_extractor.py
  test_audio_splitter.py
  test_cli.py
  test_pipeline.py
  test_subtitle_generator.py
  test_transcription_client.py
  test_config_parser.py
  test_logging_config.py
  test_formats_and_batch.py
  test_progress_reporting.py
  test_integration.py              # gated integration tests (see below)
  test_main.py
  test_core_cancel.py
  test_core_cost.py
  test_core_path_utils.py
  test_core_pipeline_structured.py
  test_db_models.py
  test_db_migrations.py             # alembic upgrade head on an ephemeral SQLite
  test_queue_claim.py
  test_queue_events.py              # fakeredis pub/sub tests (see below)
  test_reaper.py
  test_worker_progress.py
  test_worker_runner.py
  test_admin_main.py
  test_auth_passwords.py
  test_auth_sessions.py             # freezegun session-expiry tests (see below)
  test_auth_bootstrap.py
  test_api_app_lifespan.py
  test_api_auth.py
  test_api_healthz.py
  test_api_jobs_notify_bazarr.py
  test_api_jobs_stream.py           # SSE route wiring (stubbed EventSourceResponse, not real streaming)
  test_api_job_logs.py
  test_api_global_logs.py
  test_api_wanted.py
  test_api_history.py
  test_api_settings.py
  test_bazarr_client.py             # respx-mocked httpx
  test_bazarr_pathmap.py
  test_bazarr_poller.py
```

## The BDD feature suite IS the e2e layer

```
features/
  video_to_subtitles_pipeline.feature
  video_to_subtitles_format.feature
  steps/
    audio_steps.py
    video_steps.py
```

There is **no separate e2e test command**. `pyproject.toml` sets:

```toml
[tool.pytest.ini_options]
testpaths = ["tests", "features"]
python_files = ["test_*.py", "*_test.py", "*_steps.py"]
```

so a plain `pytest` run collects both the unit/integration suite under
`tests/` *and* the pytest-bdd scenarios under `features/steps/*_steps.py` in
the same session, against the same fixtures and the same coverage report.
`*_steps.py` binds `.feature` scenarios via `@scenario(...)` decorators, e.g.:

```python
@scenario('../video_to_subtitles_pipeline.feature', 'Convert single video file to SRT')
def test_convert_single_video():
    pass
```

If you're looking for "the e2e tests," this is it — don't go looking for a
separate `make e2e` or a second pytest invocation. There is currently one
`@pytest.mark.xfail`-free BDD suite; treat scenario failures with the same
severity as unit test failures.

## Exit-code contract

**CLI (`audio_to_subs/cli.py`, `python -m audio_to_subs` / `audio-to-subs`):**

| Exit code | Meaning |
|---|---|
| `0` | Success (including `--version`) |
| `1` | General failure: missing `--input`/`--output`/API key, `ConfigError`, `PipelineError`, any unexpected exception, or `--config` combined with `--input`/`--output` |
| `2` | Output directory exists but is not writable, or cannot be created (`_validate_output_directory`) |

`audio_to_subs/admin/__main__.py` follows the standard `sys.exit(main())`
pattern — its subcommands (`set-password`, `db-init`, `whoami`) return `0` on
success and a non-zero `int` on failure; check the specific subcommand's
return path if you need a precise code.

**Test runner (`pytest`, as invoked by `.github/workflows/tests.yml` via a
bare `pytest`):** standard pytest exit codes apply and are what gates the CI
job —

| Exit code | Meaning |
|---|---|
| `0` | All collected tests (unit + BDD) passed |
| `1` | At least one test failed |
| `2` | Test execution was interrupted |
| `3` | Internal pytest error |
| `4` | pytest command-line usage error |
| `5` | No tests were collected |

CI treats any non-zero `pytest` exit as a failed job; there's no separate
threshold or "warnings only" mode.

## Centralized fixtures (`tests/conftest.py`)

All fixtures live in one `conftest.py` — there's no per-package conftest
layering. Key pieces:

**`_test_environment` (autouse)** — runs for every test. Points
`DATABASE_URL` at a per-test SQLite file under `tmp_path` (not `:memory:`, so
alembic/async/sync all share one file), sets `SESSION_SECRET`,
`ADMIN_USERNAME`/`ADMIN_PASSWORD`, and `BEHIND_TLS=false`. Clears the
module-level singletons (`_db_base._async_engines`, `_db_base._sync_engine`,
`_api_settings._settings`, `_auth_sessions._session_manager`) before and
after each test so nothing leaks across tests. Also synchronously creates the
schema and seeds the `admin` user directly (bypassing the FastAPI lifespan),
so DB-only tests work even without hitting the app.

**`api_client`** — an unauthenticated `fastapi.testclient.TestClient` wired
to `create_app()`. Runs with the real lifespan (`raise_server_exceptions=False`),
so alembic migration and admin bootstrap execute against the per-test file
DB. Use this for testing the auth boundary itself (login, unauthenticated
401s, etc).

**`authenticated_client`** — same as `api_client`, but logs in as the seeded
`admin` user first (`POST /api/auth/login`) and returns the same client with
a valid session cookie attached. Added once router-level auth was rolled out
to (almost) every route — use this for any test exercising route *behavior*
rather than the auth boundary, since nearly all routes now require a session.

**`sync_session`** — a plain synchronous SQLAlchemy `Session` against the
same per-test DB (via `get_settings().DATABASE_URL` with the
`sqlite+aiosqlite` scheme swapped for `sqlite`). Useful for seeding fixture
rows before hitting the API through `api_client`/`authenticated_client`.

**`mock_db_session`** — a real *async* SQLAlchemy session (via
`audio_to_subs.db.session.get_async_session`) against the same per-test DB,
for tests that need async ORM access without going through the full FastAPI
stack (e.g. Bazarr poller tests).

**`mocked_pipeline_deps`** — patches all seven of `Pipeline`'s external
dependencies at their *import sites in `audio_to_subs.core.pipeline`*
(`extract_audio`, `get_audio_duration`, `needs_splitting`, `split_audio`,
`TranscriptionClient.transcribe_audio_with_timestamps`,
`SubtitleGenerator.generate`, `Path`), with sane defaults (60s duration, a
`Path` mock that reports `exists()=True` and a 1MB `stat().st_size`). Yields
a dict of the mocks keyed by name. Use this for any pipeline-behavior test
instead of hand-rolling the same seven patches.

**`make_job(**kwargs)`** — not a fixture, a plain factory function returning
a `Job` ORM instance with sensible defaults (`DONE`, `MANUAL` source,
`/test/video.mp4`, `srt`), overridable via kwargs.

## fakeredis for Redis pub/sub

`tests/test_queue_events.py` is the reference pattern. It instantiates a real
in-memory Redis with `fakeredis.aioredis.FakeRedis()`, subscribes a `pubsub()`
to the channel under test, calls the publisher function
(`audio_to_subs.queue_.events.publish_new` / `publish_progress`), and asserts
on the messages the subscriber receives:

```python
import fakeredis.aioredis

redis = fakeredis.aioredis.FakeRedis()
try:
    pubsub = redis.pubsub()
    await pubsub.subscribe("jobs:new")

    await publish_new(redis, job_id, payload)

    message = await pubsub.get_message()               # the subscribe ack
    message = await pubsub.get_message(timeout=1.0)     # the actual publish
    assert message["type"] == "message"
    assert message["channel"] == b"jobs:new"
finally:
    await pubsub.unsubscribe()
    await redis.close()
```

Note this is deliberately narrow: it exercises the publish functions in
`queue_/events.py` directly against a fake Redis, not the SSE HTTP endpoints.
`tests/test_api_jobs_stream.py` covers the SSE *routes* separately (see next
section) and does not use `fakeredis` at all — `TestClient` blocks until a
response body is fully read, so an infinite SSE stream would hang the test.
Route-wiring tests there patch `EventSourceResponse` with a lightweight
`Response` subclass that returns immediately, and assert on status code /
`content-type` rather than exercising real streaming or Redis. If you need to
prove the Redis→SSE bridge really works end-to-end, that belongs in a real
integration/manual test against a running server, not the unit suite.

## freezegun for deterministic time

`tests/test_auth_sessions.py` is the reference pattern — session-expiry and
renewal tests use `freeze_time` instead of real `time.sleep` calls:

```python
from freezegun import freeze_time

def test_validate_session_expired(self):
    manager = SessionManager(secret="test-secret", ttl=1)
    token = manager.create_session(123)

    with freeze_time("2024-01-01 00:00:00") as frozen_time:
        frozen_time.move_to("2024-01-01 00:00:02")  # advance 2s past the 1s TTL
        with pytest.raises(Exception):
            manager.validate_session(token)
```

`frozen_time.move_to(...)` (rather than a second `freeze_time` call) is the
idiom used to advance the clock mid-test — e.g. `test_renew_session` freezes,
creates a token, moves forward >1s so the token's integer `iat` timestamp is
guaranteed to differ, then renews and asserts the new token differs from the
old one. Prefer this over real sleeps anywhere a test depends on elapsed
wall-clock time (TTL expiry, renewal thresholds, timing comparisons).

## Tricky cases — what to watch for

### `test_queue_claim.py` — concurrent claims

Uses real on-disk SQLite (not `:memory:` — WAL semantics differ). Spawns
multiple threads, each opening its own connection, racing on `claim_one()`.
Asserts each job is claimed exactly once and no `database is locked`
exceptions escape.

### `test_bazarr_poller.py` — session-before-sleep regression

`test_poller_releases_session_before_sleep` verifies `run_bazarr_poller`
closes its DB session *before* the inter-poll `asyncio.wait_for` sleep, not
during it (a real bug found via `podman-compose up` integration testing that
held a write lock for the full poll interval and starved the reaper/health
check). Uses a lifecycle list recording `enter`/`exit` of the session context
manager and the `wait:N` event, asserting `exit` precedes `wait:3600`.

`test_healthz_returns_503_when_db_unavailable` (in `test_api_healthz.py`)
verifies `GET /api/healthz` returns 503 with a `database` error detail when
`get_async_session` raises `OperationalError`.

### `test_bazarr_*` — respx

`respx` mocks the httpx client used by `BazarrClient`:

```python
@respx.mock
async def test_list_wanted_movies():
    respx.get("http://bazarr/api/movies/wanted").mock(
        return_value=Response(200, json={"data": [...], "total": 1})
    )
    client = BazarrClient("http://bazarr", "key")
    page = await client.list_wanted_movies(start=0, length=50)
    assert page.total == 1
    assert respx.calls.last.request.headers["X-API-Key"] == "key"
```

## Integration tests

`tests/test_integration.py` keeps v1's pattern: marked
`@pytest.mark.integration`, gated on env vars (`MISTRAL_API_KEY` /
`TEST_VIDEO_FILE`), skipped by default. These never run in CI; they're for
local developer sanity checks against real external services.

## CI (`.github/workflows/tests.yml`)

Two jobs on push/PR to `main`:

- **`frontend`**: `npm ci`, `npm run build`, `npm run test` (vitest) in
  `frontend/`.
- **`test`**: `pip install -e ".[dev]"`, then `pytest` (collects `tests/` +
  `features/`, coverage on by default via `addopts` in `pyproject.toml`),
  `black --check`, `ruff check`, `mypy` against `audio_to_subs/`. On `main`
  only, generates and publishes the coverage badge to the `badges` branch.

There is no separate migration-smoke or e2e step in CI — `test_db_migrations.py`
inside the normal `pytest` run covers `alembic upgrade head` against an
ephemeral SQLite.
