# Queue & Worker Protocol

Queue durability lives in **SQLite**. Live wake-ups and event fan-out live in **Redis pub/sub**. Redis is not the source of truth.

## Redis channels

| Channel | Payload | Published by | Subscribed by |
|---|---|---|---|
| `jobs:new` | `{"job_id": "..."}` | API (on enqueue) | Workers |
| `jobs:progress:<job_id>` | `{"percent": int, "stage": "...", "message": "..."}` | Worker | API (per-job SSE) |
| `jobs:cancel:<job_id>` | `{}` | API (on cancel) | Worker |
| `jobs:done:<job_id>` | `{"status": "done\|failed\|cancelled", "error"?: "..."}` | Worker | API (per-job SSE) |
| `jobs:global` | fan-out of all `jobs:*` events | Worker + API | API (global SSE) |

`jobs:global` exists so the global SSE endpoint can subscribe to one channel instead of N.

## Worker lifecycle

### 1. Boot

Worker generates unique ID: `{hostname}-{pid}-{uuid_hex[:6]}`. No workers table - worker_id on jobs.worker_id is enough for forensics. On boot: runs reaper once, subscribes to `jobs:new` and `jobs:cancel:*`, attempts to claim a job.

### 2. Claim — atomic single-statement

SQLite >= 3.35 supports `RETURNING`. The claim is one statement inside a `BEGIN IMMEDIATE` transaction; WAL + `busy_timeout=5000` makes N concurrent workers safe.

```sql
UPDATE jobs
   SET status      = 'running',
       worker_id   = :worker_id,
       started_at  = CURRENT_TIMESTAMP,
       updated_at  = CURRENT_TIMESTAMP
 WHERE id = (
       SELECT id FROM jobs
        WHERE status = 'queued'
     ORDER BY priority DESC, created_at ASC
        LIMIT 1
)
 RETURNING id, media_path, output_path, language_code, output_format, source, source_ref;
```

If `RETURNING` is empty, sleep on the Redis subscription. If non-empty, run the job.

### 3. Run

Worker uses `CancelToken` and `ProgressBridge` to handle cancellation and progress. Progress writes to jobs row (debounced ~1 Hz) and publishes to Redis channels. On stage transitions, writes one row to `job_logs`.

### 4. Cancellation

API path: `POST /api/jobs/{id}/cancel` sets `cancel_requested = 1` and publishes on `jobs:cancel:<id>`.
Worker path: Pattern subscription on `jobs:cancel:*` fires `token.set()` when id matches. Pipeline checks `token.is_set()` at safe points and raises `Cancelled`. FFmpeg gets `process.terminate()` when cancel observed.

### 5. Crash recovery — the reaper

Workers bump `jobs.updated_at` on every progress write. If `updated_at` > 120s old on a `running` row, worker is presumed dead.

Reaper runs:
1. On every worker boot, before first claim
2. On a 60s asyncio timer in the API

```sql
UPDATE jobs
   SET status            = 'queued',
       worker_id         = NULL,
       progress_percent  = 0,
       progress_message  = 'Requeued after worker restart',
       updated_at        = CURRENT_TIMESTAMP
 WHERE status = 'running'
   AND updated_at < datetime('now', '-120 seconds');
```

## Concurrency notes

- WAL + `BEGIN IMMEDIATE` + `busy_timeout=5000` sufficient for 1 API + 1-3 workers
- Claim SQL is portable to Postgres
- Workers never share Python state - coordination through SQLite + Redis

## M5.6.1 Worker Fixes

- BEGIN IMMEDIATE lock release fixed: session always exits before sleep
- UUID binding for job-worker tracking
- Path resolution from detail endpoints fixed
- Logging enhanced for debugging

## M5.8 Progress Reporting

- Structured progress with stage/step tracking
- SSE architecture with Redis pub/sub to asyncio queue to SSE
- Progress debounced to avoid SQLite write storms
- Heartbeat every 15s for connection keepalive