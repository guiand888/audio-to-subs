# M2 Execution Plan — Worker + Queue + Cost

**Milestone**: M2 — Worker + queue + Pipeline cancellation + cost  
**Status**: Not Started  
**Depends on**: M0, M0.5, M1 (all complete ✅)  
**Blocks**: M3  

---

## Overview

M2 implements the end-to-end manual job workflow:
- Operator submits `POST /api/jobs {source:"manual", media_path:"..."}`
- Job is queued in database
- Worker picks up job, runs pipeline with cancellation support
- Progress streamed via SSE
- Cost calculated from Mistral usage or duration fallback
- Crash recovery via reaper

---

## Task Breakdown

### Phase 1: Core Infrastructure (can be parallelized)

#### 1.1 `audio_to_subs/core/cancel.py`
**Purpose**: Cooperative cancellation for long-running operations  
**Deliverables**:
- `CancelToken` class: thread-safe flag with `cancel()` and `is_cancelled()`
- `Cancelled` exception: raised when cancellation requested
- `cancel_token` kwarg accepted by all pipeline stages

**Implementation**:
```python
class CancelToken:
    """Thread-safe cancellation token."""
    def __init__(self):
        self._cancelled = False
        self._lock = threading.Lock()
    
    def cancel(self):
        with self._lock:
            self._cancelled = True
    
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

class Cancelled(Exception):
    """Raised when operation cancelled."""
    pass
```

#### 1.2 `audio_to_subs/core/cost.py`
**Purpose**: Extract usage from Mistral response, compute cost  
**Based on M0.5 probe findings**:
- `usage.prompt_audio_seconds`: billed audio duration
- `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens`: token counts
- `usage.prompt_tokens_details`: breakdown with `audio_tokens`, `cached_tokens`

**Deliverables**:
- `extract_usage(response)`: returns dict with usage fields or None
- `compute_cost(usage: dict | None, audio_duration: float, settings: Settings)`: returns USD cost
- Fallback: `audio_duration / 60 * rate_usd_per_minute` when usage unavailable

**Settings needed** (add to `Settings` class):
- `mistral_rate_usd_per_minute: float = 0.0` (primary billing)
- `mistral_input_token_rate_usd: float | None = None` (optional)
- `mistral_output_token_rate_usd: float | None = None` (optional)

#### 1.3 `audio_to_subs/core/pipeline.py` Updates
**Purpose**: Add cancellation and structured progress to existing pipeline  
**Changes**:
- Add `cancel_token: CancelToken | None = None` kwarg to `__init__`
- Add `structured_progress_callback: Callable[[str, int, dict], None] | None = None` kwarg
- Create `PipelineResult` dataclass with:
  - `output_path: str`
  - `audio_duration_seconds: float`
  - `mistral_usage_json: str | None`
  - `estimated_cost_usd: float | None`
  - `error_message: str | None`
- Modify `process_video()` to:
  - Check `cancel_token` at each stage boundary
  - Call `structured_progress_callback` with stage, percentage, metadata
  - Return `PipelineResult` instead of just path
- CLI remains unchanged (backward compatible)

#### 1.4 `audio_to_subs/core/audio_extractor.py` Updates
**Purpose**: Support cancellation during FFmpeg extraction  
**Changes**:
- Add `cancel_token: CancelToken | None = None` kwarg to `extract_audio()`
- Modify FFmpeg subprocess to:
  - Poll `cancel_token.is_cancelled()` periodically
  - Terminate process with SIGTERM if cancelled
  - Raise `Cancelled` exception

#### 1.5 `audio_to_subs/core/audio_splitter.py` Updates
**Purpose**: Support cancellation during FFmpeg splitting  
**Changes**:
- Add `cancel_token: CancelToken | None = None` kwarg to `split_audio()`
- Check token between segments
- Terminate FFmpeg process if cancelled

---

### Phase 2: Queue System

#### 2.1 `audio_to_subs/queue_/claim.py`
**Purpose**: Atomic job claiming with heartbeat  
**Deliverables**:
- `claim_job(session, worker_id, timeout_seconds=60)`: 
  - Atomically SELECT FOR UPDATE ... WHERE status='queued' ORDER BY priority DESC, created_at ASC LIMIT 1
  - Update: status='running', worker_id=worker_id, started_at=NOW()
  - Return Job if claimed, None if no jobs
- `heartbeat(session, job_id, worker_id)`: 
  - Update updated_at=NOW() to prevent reaping
- `release_job(session, job_id, worker_id, error_message=None)`: 
  - Update status='queued', worker_id=NULL, started_at=NULL

#### 2.2 `audio_to_subs/queue_/events.py`
**Purpose**: Progress event types and serialization  
**Deliverables**:
- `ProgressEvent` dataclass with:
  - `job_id: UUID`
  - `stage: str` (extracting, splitting, transcribing, generating, done, failed, cancelled)
  - `percentage: int` (0-100)
  - `message: str`
  - `timestamp: datetime`
  - `metadata: dict` (audio_duration, segment_count, etc.)
- `serialize_event(event) -> str`: JSON serialization for SSE
- `deserialize_event(data) -> ProgressEvent`: JSON deserialization

#### 2.3 `audio_to_subs/queue_/reaper.py`
**Purpose**: Reclaim stale running jobs  
**Deliverables**:
- `reap_stale_jobs(session, stale_after_seconds=120)`: 
  - Find jobs WHERE status='running' AND updated_at < NOW() - stale_after_seconds
  - Update: status='queued', worker_id=NULL, started_at=NULL, progress_percent=0
  - Return count of reaped jobs
- `start_reaper(interval_seconds=30)`: Background thread that calls reap periodically

---

### Phase 3: Worker

#### 3.1 `audio_to_subs/worker/__main__.py`
**Purpose**: Worker entry point  
**Deliverables**:
- CLI: `python -m audio_to_subs.worker [--worker-id ID] [--redis-url URL]`
- Main loop:
  1. Connect to Redis
  2. Start reaper thread
  3. Poll for jobs (sleep interval configurable)
  4. Run job via `runner.run_job()`
  5. Handle exceptions, update job status

#### 3.2 `audio_to_subs/worker/runner.py`
**Purpose**: Job execution logic  
**Deliverables**:
- `run_job(session, job: Job, settings: Settings)`: 
  - Create `CancelToken`
  - Create progress callback that publishes to Redis pub/sub
  - Instantiate Pipeline with cancel_token and structured_progress_callback
  - Call `pipeline.process_video()`
  - Update job row with results:
    - status='done' or 'failed' or 'cancelled'
    - output_path, audio_duration_seconds, mistral_usage_json, estimated_cost_usd
    - finished_at=NOW()
  - Log milestone events to job_logs table

#### 3.3 `audio_to_subs/worker/progress.py`
**Purpose**: Progress publishing and SSE management  
**Deliverables**:
- `ProgressPublisher` class:
  - `__init__(redis_client, job_id)`
  - `publish(event: ProgressEvent)`: Publish to Redis channel `job:progress:{job_id}`
  - `close()`: Cleanup
- SSE endpoint helper for API

---

### Phase 4: API Routes

#### 4.1 `audio_to_subs/api/routes/jobs.py`
**Purpose**: Job CRUD and management  
**Endpoints**:
- `POST /api/jobs`: Create job
  - Request: `{source: "manual"|"bazarr_movie"|"bazarr_episode", source_ref: str|null, media_path: str, language_code: str|null, output_format: str, priority: int}`
  - Validation: media_path must be absolute, reject path traversal
  - Response: 201 with job dict
- `GET /api/jobs`: List jobs
  - Query params: `status`, `source`, `limit`, `offset`, `user_id`
  - Response: paginated list of jobs
- `GET /api/jobs/{id}`: Get job detail
  - Response: job with logs and progress
- `POST /api/jobs/{id}/cancel`: Request cancellation
  - Update: cancel_requested=True
  - If worker active: worker checks token and cancels
  - Response: 200 with job

#### 4.2 `audio_to_subs/api/routes/stream.py`
**Purpose**: Server-Sent Events for progress  
**Endpoints**:
- `GET /api/jobs/stream`: Global stream of all job progress events
- `GET /api/jobs/{id}/stream`: Stream for specific job
**Implementation**:
- Use `sse-starlette` library
- Subscribe to Redis pub/sub channels
- Stream events as they arrive
- Handle client disconnect

#### 4.3 `audio_to_subs/api/routes/logs.py`
**Purpose**: Job log access  
**Endpoints**:
- `GET /api/jobs/{id}/logs`: Get all logs for job
  - Query params: `level` (debug, info, warning, error)
  - Response: list of log entries

---

### Phase 5: Integration

#### 5.1 Update `docker-compose.yml`
**Changes**:
- Add `worker` service:
  ```yaml
  worker:
    build:
      context: .
      dockerfile: Dockerfile
    image: audio-to-subs:worker
    container_name: audio-to-subs-worker
    environment:
      - DATABASE_URL=sqlite+aiosqlite:////data/audio-to-subs.db
      - REDIS_URL=redis://redis:6379/0
      - MISTRAL_API_KEY_FILE=/run/secrets/mistral_api_key
      - WORKER_ID=worker-1
    volumes:
      - audio-to-subs-data:/data
      - ./videos:/input:ro
      - ./subtitles:/output:rw
      - /tmp/audio-to-subs
    depends_on:
      - backend
      - redis
    restart: unless-stopped
    user: "1000:1000"
  ```
- Add mistral_api_key secret

#### 5.2 Update `audio_to_subs/api/app.py`
**Changes**:
- Include new routers: `jobs.router`, `stream.router`, `logs.router`
- Add cost settings to `Settings` class

---

### Phase 6: Tests

**Test files to create**:
1. `tests/test_core_cancel.py`:
   - Test CancelToken thread safety
   - Test Cancelled exception

2. `tests/test_core_cost.py`:
   - Test extract_usage with mock Mistral response
   - Test compute_cost with usage data
   - Test compute_cost with fallback (no usage)

3. `tests/test_core_pipeline_structured.py`:
   - Test pipeline with cancel_token (mock FFmpeg)
   - Test structured_progress_callback receives expected events
   - Test PipelineResult structure

4. `tests/test_queue_claim.py`:
   - Test claim_job atomicity
   - Test heartbeat
   - Test release_job

5. `tests/test_queue_reaper.py`:
   - Test reap_stale_jobs
   - Test reaper thread

6. `tests/test_worker_runner.py`:
   - Test run_job with mock pipeline
   - Test cancellation during run
   - Test error handling

7. `tests/test_api_jobs.py`:
   - Test POST /api/jobs
   - Test GET /api/jobs
   - Test GET /api/jobs/{id}
   - Test POST /api/jobs/{id}/cancel
   - Test path traversal rejection

8. `tests/test_api_stream.py`:
   - Test SSE connection
   - Test event streaming
   - Test client disconnect handling

---

## File Creation/Modification Summary

### New Files
```
audio_to_subs/core/cancel.py
audio_to_subs/core/cost.py
audio_to_subs/queue__/init__.py
audio_to_subs/queue_/claim.py
audio_to_subs/queue_/events.py
audio_to_subs/queue_/reaper.py
audio_to_subs/worker/__init__.py
audio_to_subs/worker/__main__.py
audio_to_subs/worker/runner.py
audio_to_subs/worker/progress.py
audio_to_subs/api/routes/jobs.py
audio_to_subs/api/routes/stream.py
audio_to_subs/api/routes/logs.py
tests/test_core_cancel.py
tests/test_core_cost.py
tests/test_core_pipeline_structured.py
tests/test_queue_claim.py
tests/test_queue_reaper.py
tests/test_worker_runner.py
tests/test_api_jobs.py
tests/test_api_stream.py
```

### Modified Files
```
audio_to_subs/core/pipeline.py
audio_to_subs/core/audio_extractor.py
audio_to_subs/core/audio_splitter.py
audio_to_subs/api/app.py
audio_to_subs/api/settings.py
docker-compose.yml
```

---

## Dependencies to Add

Check if already in pyproject.toml, if not add to dependencies:
- `sse-starlette==2.0.0` (for SSE support)

---

## Acceptance Criteria Checklist

- [ ] Submit manual job via `POST /api/jobs`
- [ ] SSE shows progress events (extracting, splitting, transcribing, generating)
- [ ] Job row reaches `done` with:
  - Non-null `audio_duration_seconds`
  - Non-null `estimated_cost_usd`
  - Populated `mistral_usage_json` (or NULL if probe decided fallback-only)
- [ ] `POST /api/jobs/{id}/cancel` mid-run:
  - Terminates FFmpeg within 1s
  - Row reaches `cancelled`
- [ ] Kill worker mid-run:
  - Within ≤120s row is reaped
  - Another worker (or restarted worker) re-picks it up
- [ ] `pytest` passes (all new tests green)
- [ ] `black --check` clean
- [ ] `ruff check` clean
- [ ] `mypy --strict` clean
- [ ] New code ≥ 80% coverage
- [ ] All commits conventional + `Signed-off-by`

---

## Execution Order

**Recommended parallelization** (per MILESTONES.md):
- Core changes (cancel.py, cost.py, pipeline.py, audio_extractor.py, audio_splitter.py) can be done in parallel once interfaces agreed
- Queue system (claim.py, events.py, reaper.py) can be done in parallel
- Worker (runner.py, progress.py, __main__.py) can be done in parallel
- API routes (jobs.py, stream.py, logs.py) can be done in parallel

**Merge order**:
1. Core infrastructure first (cancel, cost, pipeline updates)
2. Queue system
3. Worker
4. API routes
5. Docker-compose updates
6. Tests

---

## Commit Strategy

Single commit for M2 with message:
```
feat: implement M2 worker, queue, pipeline cancellation, and cost

- core/cancel.py: CancelToken and Cancelled for cooperative cancellation
- core/cost.py: extract_usage and compute_cost using Mistral probe findings
- core/pipeline.py: add cancel_token, structured_progress_callback, PipelineResult
- core/audio_extractor.py: accept cancel_token, terminate FFmpeg on cancel
- core/audio_splitter.py: accept cancel_token, terminate FFmpeg on cancel
- queue_/: claim.py (atomic job claiming), events.py (ProgressEvent), reaper.py (stale job recovery)
- worker/: __main__.py (CLI), runner.py (job execution), progress.py (Redis pub/sub)
- api/routes/jobs.py: create, list, detail, cancel endpoints
- api/routes/stream.py: SSE endpoints for job progress
- api/routes/logs.py: job log access
- docker-compose.yml: add worker service
- Tests: test_core_cancel.py, test_core_cost.py, test_core_pipeline_structured.py,
  test_queue_claim.py, test_queue_reaper.py, test_worker_runner.py,
  test_api_jobs.py, test_api_stream.py

Signed-off-by: Guillaume Andre <mail@guillaumea.fr>
```

---

## Quality Gates

Before commit:
1. Run `pytest tests/test_core_cancel.py tests/test_core_cost.py tests/test_core_pipeline_structured.py`
2. Run `pytest tests/test_queue_*.py tests/test_worker_*.py tests/test_api_jobs.py tests/test_api_stream.py`
3. Run `black --check audio_to_subs/ tests/`
4. Run `ruff check audio_to_subs/ tests/`
5. Run `mypy --strict audio_to_subs/`
6. Run `pytest --cov=audio_to_subs --cov-report=term-missing` and verify ≥80% on new modules
7. Manual smoke test: submit job, watch SSE, verify completion

---

## Notes

- Keep CLI backward compatible (pipeline changes are additive)
- Use existing Job model fields (already has all needed fields from M1)
- Redis used for pub/sub between worker and API for SSE
- SQLite WAL mode already configured in M1 (good for concurrent access)
- Worker and API share same database (SQLite with WAL)
- Cost calculation uses settings from database (Settings model to be extended)
