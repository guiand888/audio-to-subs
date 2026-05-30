# v2 — Testing strategy

Same conventions as v1:

- One `tests/test_<module>.py` per source module, mirroring the package tree.
- Unit tests use `unittest.mock`-style `@patch`; integration tests are marked `@pytest.mark.integration` and skip without `MISTRAL_API_KEY`.
- `pytest --cov` with the ≥80% gate on new code.
- `black` (line 88) + `ruff` + `mypy --strict` clean.

## New dev dependencies

Add to the `[dev]` extras in `pyproject.toml` and to `requirements-dev.txt`:

| Package | Pin | Purpose |
|---|---|---|
| `respx` | `==0.21.1` | httpx mocking (Bazarr client) |
| `fakeredis` | `==2.26.0` | In-memory Redis for API + worker tests |
| `pytest-asyncio` | `==0.23.8` | `async def` test support (FastAPI routes, async client) |
| `asgi-lifespan` | `==2.1.0` | Drive FastAPI lifespan inside async tests |
| `httpx[http2]` | already runtime | Used as the TestClient for async routes |

## Test layout (additions for v2)

```
tests/
  conftest.py                      # NEW: shared fixtures (db_session, redis, app, auth client)
  test_audio_extractor.py          # existing, plus cancel-token cases
  test_audio_splitter.py           # existing, plus cancel-token cases
  test_cli.py                      # existing (must pass after M0 unchanged)
  test_pipeline.py                 # existing
  test_subtitle_generator.py       # existing
  test_transcription_client.py     # existing
  test_config_parser.py            # existing
  test_logging_config.py           # existing
  test_core_cancel.py              # NEW
  test_core_cost.py                # NEW
  test_core_pipeline_structured.py # NEW
  test_db_models.py                # NEW
  test_db_migrations.py            # NEW: alembic upgrade head on empty DB
  test_queue_claim.py              # NEW
  test_queue_reaper.py             # NEW
  test_queue_events.py             # NEW
  test_worker_runner.py            # NEW
  test_bazarr_client.py            # NEW
  test_bazarr_pathmap.py           # NEW
  test_bazarr_poller.py            # NEW
  test_auth_passwords.py           # NEW
  test_auth_sessions.py            # NEW
  test_auth_bootstrap.py           # NEW
  test_api_auth.py                 # NEW
  test_api_jobs.py                 # NEW
  test_api_wanted.py               # NEW
  test_api_history.py              # NEW
  test_api_logs.py                 # NEW
  test_api_settings.py             # NEW
  test_api_stream.py               # NEW (SSE)
```

## Shared fixtures (`tests/conftest.py`)

```python
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from audio_to_subs.api.app import create_app
from audio_to_subs.db.base import Base


@pytest_asyncio.fixture
async def engine(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path/'test.db'}"
    eng = create_async_engine(url, future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()

@pytest_asyncio.fixture
async def db_session(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s

@pytest_asyncio.fixture
async def redis():
    r = FakeRedis()
    yield r
    await r.aclose()

@pytest_asyncio.fixture
async def app(engine, redis, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32bytes-aaaaaaaaaaaa")
    app = create_app(engine=engine, redis=redis)
    async with LifespanManager(app):
        yield app

@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

@pytest_asyncio.fixture
async def authed_client(client):
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    assert r.status_code == 200
    yield client
```

## Tricky cases — what to watch for

### `test_queue_claim.py` — concurrent claims

Use **real on-disk SQLite** (not `:memory:` — WAL semantics differ). Spawn N threads, each opening its own connection, racing on `claim_one()`. Insert M jobs first. Assert that:

- Each job is claimed exactly once.
- Total claims = min(N attempts × tries, M).
- No `database is locked` exceptions escape (the `busy_timeout=5000` should absorb contention).

```python
def test_n_workers_one_job(tmp_path):
    db = setup_db_with_jobs(tmp_path, n_jobs=10)
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(claim_one, db, f"w{i}") for i in range(8)]
        for f in as_completed(futures):
            results.append(f.result())
    claimed_ids = [r.id for r in results if r is not None]
    assert len(claimed_ids) == 8
    assert len(set(claimed_ids)) == 8           # uniqueness
    assert len(remaining_queued(db)) == 2
```

### `test_api_stream.py` — SSE

The hardest test. Strategy:

1. Use `httpx.AsyncClient` to open the SSE endpoint with `stream=True`.
2. From a background asyncio task, publish events to `fakeredis` on `jobs:global`.
3. Iterate `response.aiter_lines()` with a `wait_for` timeout (≤ 1 s).
4. Assert specific lines appear (`event: progress`, `data: {...}`).
5. Cancel the response → assert the bridge task in the app cleans up.

Allow a small fudge factor on timing; if flakiness becomes a problem, retry the assertion with backoff rather than longer timeouts.

### `test_core_cancel.py` — pipeline cancellation

- Spawn a thread that runs `Pipeline.process_video` with a mocked extract that sleeps 5 s while ticking progress.
- From the main thread, set the cancel token after 100 ms.
- Assert the worker thread raises `Cancelled` within 500 ms.
- For FFmpeg termination: use a subprocess sentinel (`yes > /tmp/sink`) and assert it's killed within 1 s of cancel.

### `test_bazarr_*`

`respx` mocks the httpx client:

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

### `test_auth_*`

- Use `freezegun` (or manual time mocking) for session expiry tests.
- Verify timing-attack mitigation: in `test_api_auth_timing.py`, measure login latency for `"nonexistent" + wrong password` vs. `"admin" + wrong password`. They should be within ±50 ms over 20 trials.

## Integration tests

Keep v1's pattern: marked `@pytest.mark.integration`, gated on `MISTRAL_API_KEY` and `TEST_VIDEO_FILE` env vars. Add:

- `tests/test_integration_bazarr.py` — gated on `BAZARR_URL` and `BAZARR_API_KEY`; hits a real Bazarr.
- `tests/test_integration_pipeline_v2.py` — end-to-end with a real Mistral call, asserts `audio_duration_seconds` populated and `mistral_usage` either present or properly None.

These never run in CI by default; they're for the developer's local sanity check.

## CI changes

`.github/workflows/tests.yml`:

- Add `fakeredis` to the install set (already in `[dev]` after pyproject update).
- Keep Python 3.12 as the runner version. Library still supports 3.9 — that's verified by the pin floor, not the CI matrix (mirror v1's policy).
- Run `alembic upgrade head` against an ephemeral SQLite before pytest (smoke test that migrations apply cleanly).
