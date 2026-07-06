"""SSE routes for job progress streaming."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from audio_to_subs.api.deps import SettingsDep, get_db, get_redis
from audio_to_subs.api.routes._helpers import get_job_or_404

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["stream"])

# Per-subscriber queues for fair event distribution
# Maps job_id -> list of (queue, client_id) tuples
# Each client gets its own queue so events aren't lost to other clients
_job_subscribers: dict[str, list[tuple[asyncio.Queue, str]]] = {}
_global_subscribers: list[tuple[asyncio.Queue, str]] = []


def _subscribe_job_stream(job_id: str, client_id: str) -> asyncio.Queue:
    """Create a subscriber queue for a job stream.

    Returns a queue that will receive all events for this job.
    """
    global _job_subscribers
    queue = asyncio.Queue()
    if job_id not in _job_subscribers:
        _job_subscribers[job_id] = []
    _job_subscribers[job_id].append((queue, client_id))
    return queue


def _unsubscribe_job_stream(job_id: str, client_id: str) -> None:
    """Remove a subscriber from a job stream."""
    global _job_subscribers
    if job_id in _job_subscribers:
        _job_subscribers[job_id] = [
            (q, cid) for q, cid in _job_subscribers[job_id] if cid != client_id
        ]
        if not _job_subscribers[job_id]:
            del _job_subscribers[job_id]


def _subscribe_global_stream(client_id: str) -> asyncio.Queue:
    """Create a subscriber queue for the global stream."""
    global _global_subscribers
    queue = asyncio.Queue()
    _global_subscribers.append((queue, client_id))
    return queue


def _unsubscribe_global_stream(client_id: str) -> None:
    """Remove a subscriber from the global stream."""
    global _global_subscribers
    _global_subscribers = [
        (q, cid) for q, cid in _global_subscribers if cid != client_id
    ]


async def _redis_listener_coro(
    redis: "Redis",
    queue: asyncio.Queue,
    channels: list[str],
    client_id: str,
) -> None:
    """Listen to Redis channels and forward events to queue.

    Args:
        redis: Redis async client
        queue: Queue to put events into
        channels: List of Redis channels to subscribe to
        client_id: Client ID for logging purposes
    """
    try:
        pubsub = redis.pubsub()
        await pubsub.subscribe(*channels)
        logger.debug(f"SSE client {client_id} subscribed to Redis channels: {channels}")

        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(timeout=1.0), timeout=2.0
                )
                if message and message.get("type") == "message":
                    try:
                        data = json.loads(message["data"])
                        await queue.put(data)
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.error(f"Failed to parse Redis message: {e}")
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        logger.debug(f"Redis listener cancelled for SSE client {client_id}")
        raise
    except Exception as e:
        logger.error(f"Error in Redis listener for SSE client {client_id}: {e}")
    finally:
        try:
            await pubsub.unsubscribe()
            await pubsub.close()
        except Exception as e:
            logger.debug(f"Error closing Redis pubsub: {e}")


async def _event_generator(  # noqa: C901
    request: Request,
    job_id: str | None = None,
    client_id: str | None = None,
    redis: "Redis | None" = None,
) -> AsyncGenerator[str, None]:
    """Generate SSE events for a job or globally.

    Each client gets its own subscription queue so events aren't lost
    to other clients. Polls with a 1-second timeout to detect disconnect.
    Also subscribes to Redis channels for multi-worker event distribution.

    Args:
        request: FastAPI/Starlette request used to detect client disconnect.
        job_id: Specific job ID to stream, or None for global stream.
        client_id: Unique ID for this client subscription.
        redis: Redis async client for subscribing to events from other workers.
    """
    if client_id is None:
        client_id = str(uuid4())

    if job_id:
        queue = _subscribe_job_stream(job_id, client_id)
    else:
        queue = _subscribe_global_stream(client_id)

    # Background task to listen to Redis events
    redis_listener_task = None
    if redis:
        if job_id:
            channels = [
                f"jobs:progress:{job_id}",
                f"jobs:done:{job_id}",
                f"jobs:cancel:{job_id}",
            ]
        else:
            channels = ["jobs:global"]

        redis_listener_task = asyncio.create_task(
            _redis_listener_coro(redis, queue, channels, client_id)
        )

    try:
        while True:
            if await request.is_disconnected():
                logger.debug("SSE client disconnected for job %s", job_id)
                break
            try:
                event_data = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield f"data: {json.dumps(event_data)}\n\n"
            except asyncio.TimeoutError:
                continue  # re-check disconnect on next iteration
    except asyncio.CancelledError:
        logger.debug("SSE connection cancelled for job %s", job_id)
    except Exception as e:
        logger.error("SSE error for job %s: %s", job_id, e)
    finally:
        # Clean up subscription
        if job_id:
            _unsubscribe_job_stream(job_id, client_id)
        else:
            _unsubscribe_global_stream(client_id)

        # Cancel Redis listener
        if redis_listener_task:
            redis_listener_task.cancel()
            try:
                await redis_listener_task
            except asyncio.CancelledError:
                pass


@router.get("/stream")
async def global_stream(
    request: Request,
    settings: SettingsDep,
    redis: Annotated["Redis", Depends(get_redis)],
) -> EventSourceResponse:
    """Global SSE stream for all job events.

    Returns a Server-Sent Events stream that receives notifications for all
    job lifecycle events (new, progress, cancel, done).
    """
    return EventSourceResponse(
        _event_generator(request, None, redis=redis),
        media_type="text/event-stream",
    )


@router.get("/{job_id}/stream")
async def job_stream(
    job_id: UUID,
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    settings: SettingsDep,
    redis: Annotated["Redis", Depends(get_redis)],
) -> EventSourceResponse:
    """Per-job SSE stream for progress updates.

    Returns a Server-Sent Events stream that receives notifications for
    the specific job's progress and completion events.
    """
    # Verify job exists
    await get_job_or_404(db, job_id)

    return EventSourceResponse(
        _event_generator(request, str(job_id), redis=redis),
        media_type="text/event-stream",
    )


# Functions to publish events to SSE streams (used as observer callbacks)
async def publish_to_job_stream(job_id: str, event_data: dict[str, Any]) -> None:
    """Publish an event to all subscribers of a job-specific SSE stream.

    This is registered as an observer callback with events.py.

    Args:
        job_id: Job ID to publish to
        event_data: Event data as dict
    """
    global _job_subscribers
    if job_id in _job_subscribers:
        for queue, _ in _job_subscribers[job_id]:
            try:
                queue.put_nowait(event_data)
            except asyncio.QueueFull:
                logger.warning("SSE queue full for job %s, dropping event", job_id)


async def publish_to_global_stream(event_data: dict[str, Any]) -> None:
    """Publish an event to all subscribers of the global SSE stream.

    This is registered as an observer callback with events.py.

    Args:
        event_data: Event data as dict
    """
    global _global_subscribers
    for queue, _ in _global_subscribers:
        try:
            queue.put_nowait(event_data)
        except asyncio.QueueFull:
            logger.warning("SSE global queue full, dropping event")


def register_observers() -> None:
    """Register SSE callbacks with the events module.

    Called during app startup to establish the observer callbacks
    for SSE event publishing.
    """
    from audio_to_subs.queue_ import events

    events.register_job_stream_observer(publish_to_job_stream)
    events.register_global_stream_observer(publish_to_global_stream)
    logger.info("Registered SSE observers with events module")
