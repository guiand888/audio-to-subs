# API

All routes are prefixed with `/api`. The frontend is served by Nginx at `/`, and Nginx proxies `/api` to the backend container on port 8000.

Auth is via session cookie (`parolesub_session`, `HttpOnly`, `SameSite=Lax`, `Secure` behind TLS). Unless the table below says "no", a valid session is required.

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

## Authentication

Single admin user. Multi-user-ready schema but bootstrap creates exactly one. Sessions are signed cookies using itsdangerous.

## Job Management

Jobs support full lifecycle: queued → running → done/failed/cancelled. Progress updates stream via SSE with percent, stage, and message. Cancellation is graceful with token-based propagation.

## SSE Architecture (M5.8)

Global stream emits every event from `jobs:global`. Per-job stream filters to a single id. Heartbeat emitted every 15s. Redis pub/sub bridges to SSE via asyncio queue. `proxy_buffering off` required in nginx.

## Progress Reporting

Structured progress with `progress_stage`, `step_index`, `step_total` for detailed workflow tracking. Updates debounced to avoid SQLite write storms.