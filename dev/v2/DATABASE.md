# v2 — Database schema

## Engine & file location

- **SQLite**, single file at `/data/audio-to-subs.db` inside the container, on a named volume shared between backend and worker.
- **WAL mode** mandatory. The engine factory in `audio_to_subs/db/base.py` runs these pragmas on every new connection:
  ```sql
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;
  PRAGMA busy_timeout = 5000;       -- 5s
  PRAGMA foreign_keys = ON;
  ```
- DSN: `sqlite+aiosqlite:////data/audio-to-subs.db` for the API; `sqlite:////data/audio-to-subs.db` for the worker.
- SQLAlchemy 2.x ORM. Pydantic v2 schemas live next to API routes, not on the ORM models.
- Postgres upgrade path: only `DATABASE_URL` changes (and `alembic upgrade head` against the new DB). No SQLite-only SQL in the codebase (we use `RETURNING`, which Postgres also supports).

## Schema

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK AUTOINCREMENT` | |
| `username` | `TEXT NOT NULL UNIQUE` | |
| `password_hash` | `TEXT NOT NULL` | argon2id |
| `created_at` | `TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP` | |
| `last_login_at` | `TIMESTAMP NULL` | |

Single row expected at runtime; schema is multi-user-ready for later.

### `sessions`

**Not created.** Sessions are signed cookies. See [`AUTH.md`](AUTH.md).

### `jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PK` | UUIDv4 string |
| `status` | `TEXT NOT NULL` | `CHECK (status IN ('queued','running','done','failed','cancelled'))` |
| `source` | `TEXT NOT NULL` | `CHECK (source IN ('bazarr_movie','bazarr_episode','manual'))` |
| `source_ref` | `TEXT NULL` | `radarrId`, `sonarrEpisodeId`, or NULL (manual) |
| `media_path` | `TEXT NOT NULL` | Resolved local path |
| `output_path` | `TEXT NULL` | Final subtitle path (filled on `done`) |
| `language_code` | `TEXT NULL` | ISO 639-1 or NULL = auto |
| `output_format` | `TEXT NOT NULL DEFAULT 'srt'` | |
| `priority` | `INTEGER NOT NULL DEFAULT 0` | Higher = sooner |
| `progress_percent` | `INTEGER NOT NULL DEFAULT 0` | 0–100, debounced writes |
| `progress_message` | `TEXT NULL` | |
| `cancel_requested` | `INTEGER NOT NULL DEFAULT 0` | 0/1 |
| `worker_id` | `TEXT NULL` | Set on claim |
| `audio_duration_seconds` | `REAL NULL` | Populated by worker before transcription |
| `mistral_usage_json` | `TEXT NULL` | Raw usage dict from Mistral, JSON-serialised |
| `estimated_cost_usd` | `REAL NULL` | Computed in `core/cost.py` |
| `error_message` | `TEXT NULL` | On `failed` |
| `created_at` | `TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP` | |
| `started_at` | `TIMESTAMP NULL` | Set on claim |
| `finished_at` | `TIMESTAMP NULL` | Set on terminal state |
| `updated_at` | `TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP` | Bumped on every progress write — used by reaper |

### `job_logs`

Append-only milestone log; backs the Logs page.

| Column | Type | Notes |
|---|---|---|
| `id` | `INTEGER PK AUTOINCREMENT` | |
| `job_id` | `TEXT NULL FK → jobs(id) ON DELETE CASCADE` | Nullable for server-wide log lines |
| `ts` | `TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP` | |
| `level` | `TEXT NOT NULL` | `CHECK (level IN ('debug','info','warning','error'))` |
| `message` | `TEXT NOT NULL` | |

Not for high-frequency progress events — those go to Redis only. Worker writes one row per stage transition (e.g., "extract done", "split into 3 segments", "transcribe segment 2/3", "subtitle written") plus errors. The Logs page filters by `level` and `since`.

### `settings`

| Column | Type | Notes |
|---|---|---|
| `key` | `TEXT PK` | |
| `value_json` | `TEXT NOT NULL` | Always JSON, even for scalars |
| `updated_at` | `TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP` | |

Keys (initial set, seeded on first boot from env or sensible defaults):

| Key | Type | Default | Notes |
|---|---|---|---|
| `bazarr_poll_interval_seconds` | int | `3600` | UI-editable |
| `bazarr_track_no_subs` | bool | `false` | Toggles the extra "list all + filter" scan |
| `path_mappings` | list of `[bazarr_prefix, local_prefix]` | from env `PATH_MAPPINGS_JSON` | |
| `mistral_model` | str | `voxtral-mini-latest` | |
| `mistral_rate_usd_per_minute` | float | `0.001` | Fallback only; placeholder |
| `default_language` | str/null | null | Used when job is created without one |
| `default_output_format` | str | `srt` | |
| `theme_default` | str | `auto` | UI bootstrap only |

### `bazarr_cache`

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PK` | `"movie:{radarrId}"` or `"episode:{sonarrEpisodeId}"` |
| `kind` | `TEXT NOT NULL` | `CHECK (kind IN ('movie','episode'))` |
| `ext_id` | `INTEGER NOT NULL` | radarrId or sonarrEpisodeId |
| `title` | `TEXT NOT NULL` | Display title |
| `subtitle_display` | `TEXT NULL` | "1x01 — Pilot" for episodes |
| `media_path_bazarr` | `TEXT NULL` | Raw path Bazarr reported (pre-mapping) |
| `missing_subtitles_json` | `TEXT NOT NULL` | JSON array of `{code2, code3, name, hi, forced}` |
| `has_any_subs` | `INTEGER NOT NULL` | 0/1 — used by the "no subs in any language" filter |
| `raw_json` | `TEXT NOT NULL` | Full Bazarr payload for the item |
| `fetched_at` | `TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP` | |

Stale rows whose `fetched_at` predates the latest poll start are deleted at the end of the poll.

## Indexes

```sql
CREATE INDEX ix_jobs_claim ON jobs(status, priority DESC, created_at);
CREATE INDEX ix_jobs_history ON jobs(status, finished_at DESC);
CREATE INDEX ix_jobs_dedupe ON jobs(source, source_ref);
CREATE INDEX ix_job_logs_job_ts ON job_logs(job_id, ts);
CREATE INDEX ix_bazarr_cache_kind_hasany ON bazarr_cache(kind, has_any_subs);
```

`ix_jobs_claim` matters: it's used by the claim transaction in [`QUEUE.md`](QUEUE.md). The other indexes back the obvious list/filter queries.

## Why progress lives on `jobs`, not in an events table

- Progress updates are high-frequency (multiple per second from FFmpeg/Mistral). An events table balloons fast and requires pruning.
- The UI only renders the *latest* progress for a job; historical progress samples carry no value.
- The information we *do* want to retain — stage transitions, errors, final cost — fits naturally in `job_logs` (one row per milestone), which the Logs page already needs.

## Alembic from day 1

A single initial revision encodes the v2.0 schema. We do **not** migrate from v1 — there is no v1 DB. Alembic config lives at `audio_to_subs/db/migrations/`.

```python
# audio_to_subs/db/migrations/env.py — sketch
from alembic import context
from audio_to_subs.db.base import Base
target_metadata = Base.metadata
```

Migration commands (run inside the backend container):

```bash
alembic -c audio_to_subs/db/alembic.ini revision --autogenerate -m "msg"
alembic -c audio_to_subs/db/alembic.ini upgrade head
```

The FastAPI lifespan and the worker boot both run `alembic upgrade head` (or check current rev and bail if there are pending migrations — pick one and document it in `audio_to_subs/db/base.py`).

## ORM models (sketch)

```python
# audio_to_subs/db/models.py
from datetime import datetime
from sqlalchemy import (
    String, Integer, Float, DateTime, ForeignKey, CheckConstraint,
    Index, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','done','failed','cancelled')",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "source IN ('bazarr_movie','bazarr_episode','manual')",
            name="ck_jobs_source",
        ),
        Index("ix_jobs_claim", "status", "priority", "created_at"),
        Index("ix_jobs_history", "status", "finished_at"),
        Index("ix_jobs_dedupe", "source", "source_ref"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String)
    media_path: Mapped[str] = mapped_column(String, nullable=False)
    output_path: Mapped[str | None] = mapped_column(String)
    language_code: Mapped[str | None] = mapped_column(String)
    output_format: Mapped[str] = mapped_column(String, server_default=text("'srt'"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    progress_message: Mapped[str | None] = mapped_column(String)
    cancel_requested: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String)
    audio_duration_seconds: Mapped[float | None] = mapped_column(Float)
    mistral_usage_json: Mapped[str | None] = mapped_column(String)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False)

    logs: Mapped[list["JobLog"]] = relationship(back_populates="job", cascade="all, delete-orphan")
```

`JobLog`, `Setting`, `BazarrCache` follow the same shape; full code is left to implementation.
