"""SSE routes for job progress streaming."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from audio_to_subs.api.deps import SettingsDep, get_db, get_redis
from audio_to_subs.api.routes._helpers import get_job_or_404

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["stream"])

# SSE comment frame emitted on the idle loop every HEARTBEAT_INTERVAL_SECONDS
# to keep the connection alive through proxies and to make dropped connections
# detectable. Browsers ignore comment frames (per the SSE spec) but the bytes
# on the wire prevent idle-timeout disconnects.
HEARTBEAT_INTERVAL_SECONDS = 15.0


def _subscribe_job_stream(job_id: str, client_id: str) -> asyncio.Queue[dict[str, Any]]:
    """Create a subscriber queue for a job stream.

    Returns a queue that will receive all events for this job from the
    client's Redis listener. (Per-client delivery is handled by the
    per-subscription queue created here, not a shared fan-out list.)
    """
    return asyncio.Queue()


def _unsubscribe_job_stream(job_id: str, client_id: str) -> None:
    """No-op: per-client queues are GC'd with the SSE connection."""
    return None


def _subscribe_global_stream(client_id: str) -> asyncio.Queue[dict[str, Any]]:
    """Create a subscriber queue for the global stream."""
    return asyncio.Queue()


def _unsubscribe_global_stream(client_id: str) -> None:
    """No-op: per-client queues are GC'd with the SSE connection.

    M5.8 (#3, verified): the in-process observer fan-out
    (register_*_observer / publish_to_*_stream) was removed. All SSE delivery now
    goes through Redis pub/sub only, so each event reaches a client exactly once.
    Do NOT reintroduce a duplicate in-process delivery path.
    """
    return None


async def _redis_listener_coro(
    redis: "Redis",
    queue: asyncio.Queue[dict[str, Any]],
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

        # Signal readiness so the client knows its subscription is active.
        # This is critical for the Wanted-list refresh flow: pub/sub has no
        # backlog, so if the client POSTs /api/wanted/refresh before this
        # subscribe() completed, early refresh_progress / refresh_done events
        # would be silently dropped. Waiting for stream_ready on the client
        # guarantees the subscription is in place before the bg task starts.
        await queue.put({"event": "stream_ready"})

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
        last_yield = time.monotonic()
        while True:
            if await request.is_disconnected():
                logger.debug("SSE client disconnected for job %s", job_id)
                break
            try:
                event_data = await asyncio.wait_for(queue.get(), timeout=1.0)
                last_yield = time.monotonic()
                yield f"data: {json.dumps(event_data)}\n\n"
            except asyncio.TimeoutError:
                # No real event in the last 1s. Emit a heartbeat comment frame
                # at most once per HEARTBEAT_INTERVAL_SECONDS so idle
                # connections stay alive through proxies without flooding the
                # log. The leading ": " marks this as a comment per the SSE
                # spec; EventSource ignores it but the bytes hit the wire.
                now = time.monotonic()
                if now - last_yield >= HEARTBEAT_INTERVAL_SECONDS:
                    last_yield = now
                    yield ": keepalive\n\n"
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
    job_id: str,
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
