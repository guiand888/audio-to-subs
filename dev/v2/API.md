# v2 — HTTP API

All routes are prefixed with `/api`. The frontend is served by Nginx at `/`, and Nginx proxies `/api` to the backend container on port 8000.

Auth is via session cookie (`ats_session`, `HttpOnly`, `SameSite=Lax`, `Secure` behind TLS). See [`AUTH.md`](AUTH.md). Unless the table below says "no", a valid session is required.

Pydantic v2 schemas back every request/response. Field validation errors surface as FastAPI's default 422.

## Route table

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | no | Username + password → session cookie |
| POST | `/api/auth/logout` | yes | Clears the session cookie |
| GET  | `/api/auth/me` | yes | Returns the current user |
| GET  | `/api/healthz` | no | 200 OK; checks DB + Redis |
| GET  | `/api/wanted` | yes | List Bazarr "wanted" items (reads `bazarr_cache`) |
| POST | `/api/jobs` | yes | Enqueue a transcription job |
| GET  | `/api/jobs` | yes | Paged list of jobs |
| GET  | `/api/jobs/{id}` | yes | Single job detail |
| POST | `/api/jobs/{id}/cancel` | yes | Request cancellation |
| GET  | `/api/jobs/{id}/logs` | yes | Job's milestone log |
| GET  | `/api/jobs/stream` | yes | SSE — global event stream |
| GET  | `/api/jobs/{id}/stream` | yes | SSE — single job |
| GET  | `/api/history` | yes | Jobs in terminal state with aggregates |
| GET  | `/api/logs` | yes | Server-wide log entries |
| GET  | `/api/settings` | yes | Read all settings |
| PATCH| `/api/settings` | yes | Partial update of settings |
| POST | `/api/jobs/{id}/notify-bazarr` | yes | Manually re-trigger Bazarr rescan |

## Schemas (sketch)

### Auth

```python
class LoginRequest(BaseModel):
    username: str
    password: str

class UserOut(BaseModel):
    id: int
    username: str
```

`POST /api/auth/login` returns `{"user": UserOut}` and sets the session cookie. `POST /api/auth/logout` returns 204.

### Wanted

```python
class MissingSubtitle(BaseModel):
    code2: str
    code3: str | None = None
    name: str | None = None
    hi: bool = False
    forced: bool = False

class WantedItem(BaseModel):
    kind: Literal["movie", "episode"]
    ext_id: int                  # radarrId or sonarrEpisodeId
    title: str
    subtitle_display: str | None # "1x01 — Pilot" for episodes, None for movies
    media_path: str              # post-pathmap, what the worker will see
    missing: list[MissingSubtitle]
    has_any_subs: bool
    active_job_id: str | None    # if there's a queued/running job for this item

class WantedPage(BaseModel):
    items: list[WantedItem]
    total: int
```

`GET /api/wanted` query params:

| Param | Type | Notes |
|---|---|---|
| `type` | `movies\|episodes\|all` | default `all` |
| `search` | str | substring match on `title` (and `subtitle_display` for episodes), case-insensitive |
| `page` | int | 1-based, default 1 |
| `page_size` | int | default 50, max 200 |
| `only_no_subs` | bool | when true, filter to items with `has_any_subs=false` |
| `missing_lang` | str | ISO 639-1, filter to items where this language is in `missing` |

### Jobs

```python
class JobCreate(BaseModel):
    source: Literal["bazarr_movie", "bazarr_episode", "manual"]
    source_ref: str | None = None     # required for bazarr_*
    media_path: str | None = None     # required for manual
    language_code: str | None = None
    output_format: Literal["srt", "vtt", "webvtt", "sbv"] = "srt"
    priority: int = 0

class JobOut(BaseModel):
    id: str
    status: Literal["queued","running","done","failed","cancelled"]
    source: Literal["bazarr_movie","bazarr_episode","manual"]
    source_ref: str | None
    media_path: str
    output_path: str | None
    language_code: str | None
    output_format: str
    priority: int
    progress_percent: int
    progress_message: str | None
    cancel_requested: bool
    worker_id: str | None
    audio_duration_seconds: float | None
    estimated_cost_usd: float | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

class JobPage(BaseModel):
    items: list[JobOut]
    total: int
```

`POST /api/jobs` behaviour:

- `bazarr_movie` / `bazarr_episode`: backend looks up the cached row, runs `bazarr/pathmap.translate(...)` to compute `media_path`, derives a default `output_path` (`{video_dir}/{video_stem}.{lang}.{ext}`).
- `manual`: `media_path` must be supplied and must exist (the backend can check via `os.path.exists` — the worker shares the volume).
- Reject duplicates: if a `queued` or `running` job already exists for `(source, source_ref)` (or for `(source='manual', media_path)`), return 409 with the existing job.
- Publish `jobs:new` on success.

### History

```python
class HistoryItem(BaseModel):
    id: str
    source: str
    source_ref: str | None
    title: str | None         # resolved from bazarr_cache when possible
    media_path: str
    output_path: str | None
    language_code: str | None
    output_format: str
    status: Literal["done","failed","cancelled"]
    audio_duration_seconds: float | None
    estimated_cost_usd: float | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None

class HistoryTotals(BaseModel):
    cost_usd: float
    duration_seconds: float
    count: int

class HistoryPage(BaseModel):
    items: list[HistoryItem]
    total: int
    totals: HistoryTotals     # for the current filter window
```

`GET /api/history` query params: `from`, `to` (ISO datetimes), `status`, `language_code`, `source`, `page`, `page_size`.

### Logs

```python
class LogEntry(BaseModel):
    id: int
    job_id: str | None
    ts: datetime
    level: Literal["debug","info","warning","error"]
    message: str

class LogsPage(BaseModel):
    items: list[LogEntry]
    total: int
```

`GET /api/logs` query params: `level`, `job_id`, `since` (ISO datetime), `page`, `page_size`.

### Settings

```python
class SettingsOut(BaseModel):
    bazarr_poll_interval_seconds: int
    bazarr_track_no_subs: bool
    path_mappings: list[tuple[str, str]]
    mistral_model: str
    mistral_rate_usd_per_minute: float
    default_language: str | None
    default_output_format: str
    theme_default: Literal["light","dark","auto"]

class SettingsPatch(BaseModel):
    bazarr_poll_interval_seconds: int | None = None
    bazarr_track_no_subs: bool | None = None
    path_mappings: list[tuple[str, str]] | None = None
    mistral_model: str | None = None
    mistral_rate_usd_per_minute: float | None = None
    default_language: str | None = None
    default_output_format: str | None = None
    theme_default: Literal["light","dark","auto"] | None = None
```

`PATCH /api/settings` only persists keys that are present (non-None) — Pydantic's `model_dump(exclude_unset=True)`.

## SSE — `/api/jobs/stream` and `/api/jobs/{id}/stream`

```
event: progress
data: {"job_id":"...","percent":42,"stage":"transcribe","message":"segment 2/3"}

event: done
data: {"job_id":"...","status":"done"}

event: new
data: {"job_id":"...","source":"bazarr_episode","source_ref":"123"}
```

- Global stream emits **every** event from `jobs:global`.
- Per-job stream filters to a single id.
- Heartbeat: emit a comment line every 15 s so proxies don't drop idle connections (Nginx `proxy_read_timeout` is set to 24h anyway, but heartbeats are cheap insurance).
- The endpoint uses `sse-starlette` and bridges Redis pub/sub → asyncio queue → SSE response. On client disconnect, the bridge task cancels.
- `proxy_buffering off` MUST be set in `frontend/nginx.conf` for the SSE chunked transfer to flow.

## Error model

Standard FastAPI: 400 (validation), 401 (no/expired session), 403 (no permission — reserved for future multi-user), 404, 409 (duplicate job), 422 (Pydantic), 500. Error body shape:

```json
{"detail": "<message>"}
```

Auth failures clear the cookie via `Set-Cookie: ats_session=; Max-Age=0`.

## Healthz

```
GET /api/healthz → 200 {"db": "ok", "redis": "ok"}
```

Returns 503 with `{"db": "...", "redis": "..."}` when one of the dependencies is down. Used by Compose's `healthcheck:` block.
