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
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Channel names per QUEUE.md
CHANNEL_NEW = "jobs:new"
CHANNEL_GLOBAL = "jobs:global"


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


async def publish_refresh_done(
    redis: Redis,
    refresh_id: str,
    status: str,
    movies_processed: int = 0,
    episodes_processed: int = 0,
    error: str | None = None,
) -> None:
    """Publish completion of a Wanted-list refresh.

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
