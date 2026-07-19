"""Redis event publishing for job queue.

Provides pub/sub helpers for job lifecycle events.
See QUEUE.md for channel and payload specifications.

All SSE delivery is routed through Redis pub/sub (per QUEUE.md's documented
architecture). There is intentionally no in-process observer path: every
SSE-serving process subscribes to the relevant Redis channel for each connected
client, so worker-originated and API-originated events share a single delivery
mechanism and each event reaches a client exactly once.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Channel names per QUEUE.md
CHANNEL_NEW = "jobs:new"
CHANNEL_GLOBAL = "jobs:global"

# Wanted-list refresh state is persisted in Redis (with TTL) so a client that
# misses the terminal SSE event - because its EventSource opened after the
# refresh finished, dropped mid-stream, or was asleep - can recover via
# GET /api/wanted/refresh/{refresh_id}. Pub/sub has no backlog, so without
# this side-channel a fast refresh can publish refresh_done before any
# subscriber exists and the UI would hang on "Refreshing..." forever.
REFRESH_STATE_KEY_PREFIX = "refresh:state:"
REFRESH_STATE_TTL_SECONDS = 600

# Live per-job progress is mirrored into a Redis hash so the REST read paths
# (GET /api/jobs, GET /api/jobs/{id}, and the Wanted endpoints) can serve fresh
# progress for running jobs. The worker publishes to pub/sub for the live SSE
# stream AND writes this snapshot for the polling/REST fallback. The DB no
# longer stores a progress column - Redis is the sole source for in-flight
# progress, and a terminal job's progress is derived from its status (done =>
# 100, otherwise 0). A generous TTL lets an abandoned key expire on its own;
# each progress event refreshes it.
JOB_PROGRESS_KEY_PREFIX = "job:progress:"
JOB_PROGRESS_TTL_SECONDS = 3600


async def set_refresh_state(
    redis: Redis,
    refresh_id: str,
    state: dict[str, Any],
    ttl_seconds: int = REFRESH_STATE_TTL_SECONDS,
) -> None:
    """Persist the latest snapshot of a refresh run keyed by ``refresh_id``.

    Overwrites any prior state for the same id and resets the TTL. Safe to
    call repeatedly from the background task's progress callback.
    """
    try:
        payload = {**state, "updated_at": datetime.now(timezone.utc).isoformat()}
        await redis.set(
            f"{REFRESH_STATE_KEY_PREFIX}{refresh_id}",
            json.dumps(payload),
            ex=ttl_seconds,
        )
    except Exception as e:  # noqa: BLE001
        # Persistence is best-effort: a failure here must not break the
        # refresh itself, only the recovery path.
        logger.error("Failed to persist refresh state for %s: %s", refresh_id, e)


async def get_refresh_state(redis: Redis, refresh_id: str) -> dict[str, Any] | None:
    """Read the persisted snapshot for ``refresh_id``, or ``None`` if missing.

    Returns ``None`` when the key never existed or has expired (TTL elapsed),
    so callers can treat both as "unknown" and surface an error to the user.
    """
    raw = await redis.get(f"{REFRESH_STATE_KEY_PREFIX}{refresh_id}")
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        # json.loads returns Any; cast to the declared dict shape so mypy
        # sees this as dict[str, Any] | None rather than Any | None.
        state: dict[str, Any] = json.loads(raw)
        return state
    except (json.JSONDecodeError, TypeError) as e:
        logger.error("Malformed refresh state for %s: %s", refresh_id, e)
        return None


async def _publish(
    redis: Redis,
    channel: str,
    payload: dict[str, Any],
) -> None:
    """Publish a message to a Redis channel.

    Args:
        redis: Redis async client
        channel: Channel name to publish to
        payload: Message payload as a dict
    """
    try:
        message = json.dumps(payload)
        await redis.publish(channel, message)
        logger.debug(f"Published to {channel}: {payload}")
    except Exception as e:
        logger.error(f"Failed to publish to {channel}: {e}")
        raise


async def set_job_progress(
    redis: Redis,
    job_id: str,
    percent: int,
    stage: str,
    message: str,
    step_index: int | None = None,
    step_total: int | None = None,
) -> None:
    """Mirror live job progress into a Redis hash for the REST read paths.

    The worker calls this on every progress event (in addition to the pub/sub
    publish used for the SSE stream). ``GET /api/jobs`` overlays this snapshot
    onto non-terminal jobs so polling reflects fresh progress without waiting
    for the debounced DB write. The key carries a generous TTL that each event
    refreshes, so a key for an abandoned job expires on its own.

    The HSET and EXPIRE are issued through a single pipeline so they cost one
    round-trip instead of two.

    Args:
        redis: Redis async client
        job_id: Job id
        percent: Progress percentage (0-100)
        stage: Current pipeline stage
        message: Progress message
        step_index: Optional 1-based step number within the job
        step_total: Optional total number of steps for the job
    """
    key = f"{JOB_PROGRESS_KEY_PREFIX}{job_id}"
    try:
        async with redis.pipeline() as pipe:
            await pipe.hset(  # type: ignore[misc]
                key,
                mapping={
                    "percent": percent,
                    "stage": stage or "",
                    "message": message or "",
                    "step_index": step_index if step_index is not None else "",
                    "step_total": step_total if step_total is not None else "",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            await pipe.expire(key, JOB_PROGRESS_TTL_SECONDS)
            await pipe.execute()
    except Exception as e:  # noqa: BLE001
        # Best-effort: a snapshot miss must never break the job. The SSE
        # pub/sub path is independent, and terminal progress is derived from
        # job status (no DB column is involved).
        logger.error("Failed to persist live progress snapshot for %s: %s", job_id, e)


def _decode_progress_hash(raw: dict[Any, Any]) -> dict[str, Any]:
    """Normalize a raw Redis hash (bytes or str keys/values) to str-keyed str.

    Single source of truth for decoding job-progress snapshots so the read
    paths don't each re-implement bytes handling.
    """
    return {
        (k.decode() if isinstance(k, bytes) else k): (
            v.decode() if isinstance(v, bytes) else v
        )
        for k, v in raw.items()
    }


async def get_job_progress(redis: Redis, job_id: str) -> dict[str, Any] | None:
    """Read the live progress snapshot for ``job_id``, or ``None`` if absent.

    Returns ``None`` on a Redis error as well as on a missing key, so callers
    can treat both as "no fresh data" and fall back to the DB column.

    Args:
        redis: Redis async client
        job_id: Job id

    Returns:
        The decoded hash keyed by percent/stage/message/step_index/
        step_total/updated_at, or ``None``.
    """
    key = f"{JOB_PROGRESS_KEY_PREFIX}{job_id}"
    try:
        raw = await redis.hgetall(key)  # type: ignore[misc]
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to read live progress snapshot for %s: %s", job_id, e)
        return None
    if not raw:
        return None
    return _decode_progress_hash(raw)


async def get_job_progress_many(
    redis: Redis, job_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Batch-read live progress snapshots for several jobs in one round-trip.

    Mirrors ``get_job_progress`` per job but pipelines the ``HGETALL`` calls so
    the caller avoids the N+1 round-trip that a per-job loop would incur (e.g.
    ``GET /api/wanted`` over many active jobs). Jobs with no snapshot are
    simply absent from the returned dict.

    Args:
        redis: Redis async client
        job_ids: Job ids to read

    Returns:
        Mapping of job id to its decoded progress hash (only present when a
        snapshot exists and decodes without error).
    """
    if not job_ids:
        return {}
    try:
        pipe = redis.pipeline()
        for job_id in job_ids:
            pipe.hgetall(f"{JOB_PROGRESS_KEY_PREFIX}{job_id}")
        raws = await pipe.execute()
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to read batch live progress snapshots: %s", e)
        return {}
    result: dict[str, dict[str, Any]] = {}
    for job_id, raw in zip(job_ids, raws):
        if raw:
            result[job_id] = _decode_progress_hash(raw)
    return result


async def clear_job_progress(redis: Redis, job_id: str) -> None:
    """Delete the live progress snapshot for ``job_id``.

    Called when a job reaches a terminal state (so the next GET sees the DB's
    authoritative terminal progress, not a stale snapshot) and on claim/reap so
    a freshly (re)started job doesn't inherit a previous run's snapshot.

    Args:
        redis: Redis async client
        job_id: Job id
    """
    key = f"{JOB_PROGRESS_KEY_PREFIX}{job_id}"
    try:
        await redis.delete(key)
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to clear live progress snapshot for %s: %s", job_id, e)


async def publish_new(redis: Redis, job_id: str) -> None:
    """Publish a new job notification.

    Args:
        redis: Redis async client
        job_id: UUID of the newly created job
    """
    payload = {"job_id": job_id}
    # Publish to specific channel
    await _publish(redis, f"{CHANNEL_NEW}", payload)
    # Also publish to global fan-out channel
    global_payload = {"event": "new", "job_id": job_id}
    await _publish(redis, CHANNEL_GLOBAL, global_payload)


async def publish_progress(
    redis: Redis,
    job_id: str,
    percent: int,
    stage: str,
    message: str,
    step_index: int | None = None,
    step_total: int | None = None,
) -> None:
    """Publish a progress update for a job.

    Args:
        redis: Redis async client
        job_id: UUID of the job
        percent: Progress percentage (0-100)
        stage: Current pipeline stage
        message: Progress message
        step_index: Optional 1-based step number within the job
        step_total: Optional total number of steps for the job
    """
    payload = {
        "percent": percent,
        "stage": stage,
        "message": message,
        "step_index": step_index,
        "step_total": step_total,
    }
    # Publish to job-specific channel
    await _publish(redis, f"jobs:progress:{job_id}", payload)
    # Also publish to global fan-out channel
    global_payload = {"event": "progress", "job_id": job_id, **payload}
    await _publish(redis, CHANNEL_GLOBAL, global_payload)


async def publish_refresh_progress(
    redis: Redis,
    refresh_id: str,
    processed: int,
    total: int | None,
    percent: int,
    stage: str,
) -> None:
    """Publish a progress update for a Wanted-list refresh.

    Emitted on the global fan-out channel so the already-mounted global SSE
    stream carries it to every connected client. The refresh has no Job row,
    so it is identified by a refresh_id rather than a job_id.

    Also persisted to Redis under ``refresh:state:{refresh_id}`` so a client
    that misses the live event (late EventSource, reconnect after sleep) can
    recover via GET /api/wanted/refresh/{refresh_id}.

    Args:
        redis: Redis async client
        refresh_id: Unique id for this refresh run
        processed: Number of items processed so far
        total: Known total of wanted items, or None when unknown (no-subs pass)
        percent: Progress percentage (0-100), 0 when total is unknown
        stage: Human-readable current stage
    """
    payload = {
        "event": "refresh_progress",
        "refresh_id": refresh_id,
        "processed": processed,
        "total": total,
        "percent": percent,
        "stage": stage,
    }
    await _publish(redis, CHANNEL_GLOBAL, payload)
    await set_refresh_state(
        redis,
        refresh_id,
        {
            "refresh_id": refresh_id,
            "status": "started",
            "processed": processed,
            "total": total,
            "percent": percent,
            "stage": stage,
            "movies_processed": 0,
            "episodes_processed": 0,
            "error": None,
        },
    )


async def publish_refresh_done(
    redis: Redis,
    refresh_id: str,
    status: str,
    movies_processed: int = 0,
    episodes_processed: int = 0,
    error: str | None = None,
) -> None:
    """Publish completion of a Wanted-list refresh.

    Also persists the final state to Redis so a client that missed the live
    ``refresh_done`` (e.g. opened its EventSource after the refresh finished)
    can recover by polling GET /api/wanted/refresh/{refresh_id}.

    Args:
        redis: Redis async client
        refresh_id: Unique id for this refresh run
        status: Final status ('completed' or 'failed')
        movies_processed: Movies processed this run
        episodes_processed: Episodes processed this run
        error: Optional error message on failure
    """
    payload: dict[str, Any] = {
        "event": "refresh_done",
        "refresh_id": refresh_id,
        "status": status,
        "movies_processed": movies_processed,
        "episodes_processed": episodes_processed,
    }
    if error:
        payload["error"] = error
    await _publish(redis, CHANNEL_GLOBAL, payload)
    await set_refresh_state(
        redis,
        refresh_id,
        {
            "refresh_id": refresh_id,
            "status": status,
            "processed": movies_processed + episodes_processed,
            "total": None,
            "percent": 100 if status == "completed" else 0,
            "stage": status,
            "movies_processed": movies_processed,
            "episodes_processed": episodes_processed,
            "error": error,
        },
    )


async def publish_cancel(redis: Redis, job_id: str) -> None:
    """Publish a cancellation notification for a job.

    Args:
        redis: Redis async client
        job_id: UUID of the job to cancel
    """
    payload: dict[str, Any] = {}
    # Publish to job-specific channel
    await _publish(redis, f"jobs:cancel:{job_id}", payload)
    # Also publish to global fan-out channel
    global_payload = {"event": "cancel", "job_id": job_id}
    await _publish(redis, CHANNEL_GLOBAL, global_payload)


async def publish_done(
    redis: Redis,
    job_id: str,
    status: str,
    error: str | None = None,
) -> None:
    """Publish a completion notification for a job.

    Args:
        redis: Redis async client
        job_id: UUID of the job
        status: Final status ('done', 'failed', 'cancelled')
        error: Optional error message for failed jobs
    """
    payload: dict[str, Any] = {"status": status}
    if error:
        payload["error"] = error

    # Publish to job-specific channel
    await _publish(redis, f"jobs:done:{job_id}", payload)
    # Also publish to global fan-out channel
    global_payload = {"event": "done", "job_id": job_id, **payload}
    await _publish(redis, CHANNEL_GLOBAL, global_payload)
