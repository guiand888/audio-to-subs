# v2 — Queue & worker protocol

Queue durability lives in **SQLite**. Live wake-ups and event fan-out live in **Redis pub/sub**. Redis is *not* the source of truth — if it dies, jobs continue (workers fall back to a slow polling loop) and the UI loses live updates only.

## Redis channels

| Channel | Payload | Published by | Subscribed by |
|---|---|---|---|
| `jobs:new` | `{"job_id": "..."}` | API (on enqueue) | Workers |
| `jobs:progress:<job_id>` | `{"percent": int, "stage": "...", "message": "..."}` | Worker | API (per-job SSE) |
| `jobs:cancel:<job_id>` | `{}` | API (on cancel) | Worker |
| `jobs:done:<job_id>` | `{"status": "done\|failed\|cancelled", "error"?: "..."}` | Worker | API (per-job SSE) |
| `jobs:global` | fan-out of all `jobs:*` events with `{"event": "...", "job_id": "..."}` payload envelope | Worker + API | API (global SSE) |

`jobs:global` exists so the global SSE endpoint can subscribe to one channel instead of N. Workers and the API both publish to `jobs:global` *in addition to* the specific channels above (cheap; lets per-job subscribers stay cheap too).

## Worker lifecycle

### 1. Boot

```python
worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
```

No `workers` table — `worker_id` on `jobs.worker_id` is enough for forensics. On boot the worker:

1. Runs the **reaper** once (see below).
2. Subscribes to `jobs:new` and `jobs:cancel:*` (pattern subscription).
3. Attempts to claim a job. If none, blocks on the Redis subscription.

### 2. Claim — atomic single-statement

SQLite ≥ 3.35 supports `RETURNING`. The claim is one statement inside a `BEGIN IMMEDIATE` transaction; WAL + `busy_timeout=5000` makes N concurrent workers safe.

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

Reference: `audio_to_subs/queue_/claim.py`.

### 3. Run

```python
token = CancelToken()
bridge = ProgressBridge(db_session, redis_client, job_id, token)
pipeline = Pipeline(
    api_key=settings.mistral_api_key,
    structured_progress_callback=bridge.on_event,
    cancel_token=token,
    transcription_model=settings.mistral_model,
    language=job.language_code,
)
try:
    result = pipeline.process_video(job.media_path, job.output_path, job.output_format)
    persist_success(db_session, job_id, result)
    publish_done(redis_client, job_id, "done")
    best_effort_bazarr_rescan(job)
except Cancelled:
    persist_cancelled(db_session, job_id)
    publish_done(redis_client, job_id, "cancelled")
except Exception as e:
    persist_failed(db_session, job_id, str(e))
    publish_done(redis_client, job_id, "failed", error=str(e))
```

The `ProgressBridge` (in `audio_to_subs/worker/progress.py`):

- Writes `progress_percent`, `progress_message`, and bumps `updated_at` on the `jobs` row (debounced, ~1 Hz max to avoid SQLite write storms).
- Publishes every event verbatim on `jobs:progress:<id>` and `jobs:global`.
- On stage transitions, writes one row to `job_logs` (level `info`).

### 4. Cancellation

API path:
1. `POST /api/jobs/{id}/cancel` sets `cancel_requested = 1` on the row.
2. Publishes `{}` on `jobs:cancel:<id>`.

Worker path:
1. Pattern subscription on `jobs:cancel:*` fires `token.set()` when the id matches the currently-running job.
2. `Pipeline` and `audio_extractor.extract_audio` check `token.is_set()` at safe points (between segments, between FFmpeg progress ticks) and raise `Cancelled`.
3. FFmpeg subprocess gets `process.terminate()` when cancel is observed mid-stage.

If the worker is not currently running that job (e.g., it's still queued), the API does the right thing directly: `UPDATE jobs SET status='cancelled', finished_at=CURRENT_TIMESTAMP WHERE id=:id AND status='queued'` (guarded so we don't race the claim).

### 5. Crash recovery — the reaper

Workers bump `jobs.updated_at` on every progress write. If `updated_at` is older than 120 s on a `running` row, the worker is presumed dead.

The reaper runs:
1. On every worker boot, before its first claim.
2. On a 60 s asyncio timer in the API.

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

Reference: `audio_to_subs/queue_/reaper.py`.

Two minutes of progress silence is a heuristic; it can be moved to settings if needed.

## Concurrency notes

- WAL + `BEGIN IMMEDIATE` + `busy_timeout=5000` is sufficient for 1 API + 1–3 workers. The single claim statement is the only write contention point on a hot queue.
- For more workers, the upgrade path is Postgres, not SQLite tuning. The claim SQL is portable as-is.
- Workers never share Python state. All coordination is through SQLite + Redis.

## Why pub/sub, not Redis Streams

- Durability is already handled by SQLite. Streams would duplicate state and add a cleanup story.
- The UI only cares about the latest progress. There's no consumer that benefits from replay.
- Pub/sub fits the "broadcast event" semantics naturally — multiple SSE subscribers, one publisher.

## Failure modes

| Failure | Behaviour |
|---|---|
| Worker crash mid-job | Row reaped → requeued within ≤120 s. Partial temp files cleaned on next worker boot (best effort). |
| Redis crash | Workers fall back to slow polling (`SELECT … LIMIT 1` every 10 s). UI loses live progress until reconnect; rows still update so the user can refresh manually. |
| Bazarr unreachable | Poller logs at `warning`, `bazarr_cache` keeps last good data. Wanted page still works against stale cache. |
| SQLite locked > `busy_timeout` | Claim retries one full cycle (one missed `jobs:new` notification); a follow-up notification or the next poll catches the missed job. Worth a Prometheus counter later, not in v2.0. |
| FFmpeg or Mistral hang | No timeout in v1; v2 should pass a configurable `--timeout` to FFmpeg and use httpx timeouts for the Mistral SDK if it exposes them. If not exposed, fall back to a thread-level watchdog that sets `token.set()` after N seconds. |

## Public API of `audio_to_subs/queue_/`

```python
# claim.py
def claim_one(session: Session, worker_id: str) -> ClaimedJob | None: ...

# events.py
def publish_new(redis: Redis, job_id: str) -> None: ...
def publish_progress(redis: Redis, job_id: str, percent: int, stage: str, message: str) -> None: ...
def publish_cancel(redis: Redis, job_id: str) -> None: ...
def publish_done(redis: Redis, job_id: str, status: str, error: str | None = None) -> None: ...

# reaper.py
def reap_stale_running(session: Session, stale_seconds: int = 120) -> int: ...
```
