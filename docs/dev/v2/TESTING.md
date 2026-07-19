# Testing

## Test layout

One `tests/test_<module>.py` per source module, mirroring package tree. BDD feature suite IS the e2e layer - no separate e2e command.

## Dev dependencies

pytest, pytest-bdd, pytest-cov, pytest-asyncio, freezegun, respx, genbadge[coverage], black, ruff, mypy.

## Centralized fixtures

All in `tests/conftest.py`:
- `_test_environment` (autouse): Sets up per-test SQLite DB, seeds admin user
- `api_client`: Unauthenticated TestClient
- `authenticated_client`: Same but logged in as admin
- `sync_session`: Sync SQLAlchemy session
- `mock_db_session`: Real async SQLAlchemy session
- `mocked_pipeline_deps`: Patches Pipeline external dependencies
- `make_job(**kwargs)`: Factory function for Job ORM instances

## Key test patterns

- `fakeredis` for Redis pub/sub tests
- `freezegun` for deterministic time (session expiry, renewal)
- `respx` for Bazarr client HTTP mocking
- Concurrent claims tested with real on-disk SQLite
- Session-before-sleep regression tests (M5.6.1 fix)

## CI

Two jobs: frontend (npm ci, build, test) and backend (pytest with coverage, black, ruff, mypy).

## Quality bar

- pytest passes
- black --check clean
- ruff check clean  
- mypy --strict clean
- New code >= 80% coverage
- Signed-off-by in all commits