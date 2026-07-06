"""Redis event publishing for job queue.

Provides pub/sub helpers for job lifecycle events.
See QUEUE.md for channel and payload specifications.

Supports observer callbacks for SSE and other subscribers to hook into
job lifecycle events without coupling to the event publishing module.
"""

import json
import logging
from collections.abc import Awaitable
from typing import Any, Callable

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Channel names per QUEUE.md
CHANNEL_NEW = "jobs:new"
CHANNEL_GLOBAL = "jobs:global"

# Observer callback type: async function that takes (job_id, event_data) or just (event_data)
SSEObserverCallback = Callable[
    [str, dict[str, Any]], Awaitable[None]
]  # publish_to_job_stream signature
GlobalObserverCallback = Callable[
    [dict[str, Any]], Awaitable[None]
]  # publish_to_global_stream signature

# Registered observers for events
_job_stream_observers: list[SSEObserverCallback] = []
_global_stream_observers: list[GlobalObserverCallback] = []


def register_job_stream_observer(callback: SSEObserverCallback) -> None:
    """Register an observer callback for job stream events.

    The callback will be invoked with (job_id, event_data) when job events are published.

    Args:
        callback: Async function(job_id: str, event_data: dict) -> None
    """
    _job_stream_observers.append(callback)
    logger.debug(f"Registered job stream observer: {callback.__name__}")


def register_global_stream_observer(callback: GlobalObserverCallback) -> None:
    """Register an observer callback for global stream events.

    The callback will be invoked with (event_data,) when global events are published.

    Args:
        callback: Async function(event_data: dict) -> None
    """
    _global_stream_observers.append(callback)
    logger.debug(f"Registered global stream observer: {callback.__name__}")


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


async def _notify_job_stream_observers(job_id: str, event_data: dict[str, Any]) -> None:
    """Notify all job stream observers of an event.

    Args:
        job_id: Job ID
        event_data: Event data to send
    """
    for observer in _job_stream_observers:
        try:
            await observer(job_id, event_data)
        except Exception as e:
            logger.error(
                f"Error notifying job stream observer {observer.__name__}: {e}"
            )


async def _notify_global_stream_observers(event_data: dict[str, Any]) -> None:
    """Notify all global stream observers of an event.

    Args:
        event_data: Event data to send
    """
    for observer in _global_stream_observers:
        try:
            await observer(event_data)
        except Exception as e:
            logger.error(
                f"Error notifying global stream observer {observer.__name__}: {e}"
            )


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

    # Notify observers
    job_payload = {"event": "new", "job_id": job_id}
    await _notify_job_stream_observers(job_id, job_payload)
    await _notify_global_stream_observers(global_payload)


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
    global_payload = {"event": "progress", "job_id": job_id, **payload}
    await _publish(redis, CHANNEL_GLOBAL, global_payload)

    # Notify observers
    job_payload = {"event": "progress", "job_id": job_id, **payload}
    await _notify_job_stream_observers(job_id, job_payload)
    await _notify_global_stream_observers(global_payload)


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
    global_payload = {"event": "cancel", "job_id": job_id}
    await _publish(redis, CHANNEL_GLOBAL, global_payload)

    # Notify observers
    job_payload = {"event": "cancel", "job_id": job_id}
    await _notify_job_stream_observers(job_id, job_payload)
    await _notify_global_stream_observers(global_payload)


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

    # Notify observers
    job_payload = {"event": "done", "job_id": job_id, **payload}
    await _notify_job_stream_observers(job_id, job_payload)
    await _notify_global_stream_observers(global_payload)
