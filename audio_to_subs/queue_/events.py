"""Redis event publishing for job queue.

Provides pub/sub helpers for job lifecycle events.
See QUEUE.md for channel and payload specifications.
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
    await _publish(redis, CHANNEL_GLOBAL, {"event": "new", "job_id": job_id})


async def publish_progress(
    redis: Redis,
    job_id: str,
    percent: int,
    stage: str,
    message: str,
) -> None:
    """Publish a progress update for a job.

    Args:
        redis: Redis async client
        job_id: UUID of the job
        percent: Progress percentage (0-100)
        stage: Current pipeline stage
        message: Progress message
    """
    payload = {
        "percent": percent,
        "stage": stage,
        "message": message,
    }
    # Publish to job-specific channel
    await _publish(redis, f"jobs:progress:{job_id}", payload)
    # Also publish to global fan-out channel
    await _publish(redis, CHANNEL_GLOBAL, {"event": "progress", "job_id": job_id, **payload})


async def publish_cancel(redis: Redis, job_id: str) -> None:
    """Publish a cancellation notification for a job.

    Args:
        redis: Redis async client
        job_id: UUID of the job to cancel
    """
    payload = {}
    # Publish to job-specific channel
    await _publish(redis, f"jobs:cancel:{job_id}", payload)
    # Also publish to global fan-out channel
    await _publish(redis, CHANNEL_GLOBAL, {"event": "cancel", "job_id": job_id})


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
    await _publish(redis, CHANNEL_GLOBAL, {"event": "done", "job_id": job_id, **payload})
