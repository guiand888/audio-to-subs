"""SSE routes for job progress streaming."""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Annotated, Any, AsyncGenerator
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from audio_to_subs.api.deps import SettingsDep, get_db
from audio_to_subs.db.models import Job, JobStatus

if TYPE_CHECKING:
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
    _global_subscribers = [(q, cid) for q, cid in _global_subscribers if cid != client_id]


async def _event_generator(
    request: Request,
    job_id: str | None = None,
    client_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Generate SSE events for a job or globally.

    Each client gets its own subscription queue so events aren't lost
    to other clients. Polls with a 1-second timeout to detect disconnect.

    Args:
        request: FastAPI/Starlette request used to detect client disconnect.
        job_id: Specific job ID to stream, or None for global stream.
        client_id: Unique ID for this client subscription.
    """
    if client_id is None:
        client_id = str(uuid4())

    if job_id:
        queue = _subscribe_job_stream(job_id, client_id)
    else:
        queue = _subscribe_global_stream(client_id)

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


@router.get("/stream")
async def global_stream(
    request: Request,
    settings: SettingsDep,
) -> EventSourceResponse:
    """Global SSE stream for all job events.

    Returns a Server-Sent Events stream that receives notifications for all
    job lifecycle events (new, progress, cancel, done).
    """
    return EventSourceResponse(
        _event_generator(request, None),
        media_type="text/event-stream",
    )


@router.get("/{job_id}/stream")
async def job_stream(
    job_id: UUID,
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    settings: SettingsDep,
) -> EventSourceResponse:
    """Per-job SSE stream for progress updates.

    Returns a Server-Sent Events stream that receives notifications for
    the specific job's progress and completion events.
    """
    # Verify job exists (convert UUID to string for String(36) column comparison)
    result = await db.execute(
        select(Job).where(Job.id == str(job_id))
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    return EventSourceResponse(
        _event_generator(request, str(job_id)),
        media_type="text/event-stream",
    )


# Functions to publish events to SSE streams
def publish_to_job_stream(job_id: str, event_data: dict[str, Any]) -> None:
    """Publish an event to all subscribers of a job-specific SSE stream.

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


def publish_to_global_stream(event_data: dict[str, Any]) -> None:
    """Publish an event to all subscribers of the global SSE stream.

    Args:
        event_data: Event data as dict
    """
    global _global_subscribers
    for queue, _ in _global_subscribers:
        try:
            queue.put_nowait(event_data)
        except asyncio.QueueFull:
            logger.warning("SSE global queue full, dropping event")


# Monkey-patch the queue events module to also publish to SSE
import audio_to_subs.queue_.events as events_module

_original_publish_new = events_module.publish_new
_original_publish_progress = events_module.publish_progress
_original_publish_cancel = events_module.publish_cancel
_original_publish_done = events_module.publish_done


async def patched_publish_new(redis, job_id: str) -> None:
    """Publish new job and also to SSE streams."""
    await _original_publish_new(redis, job_id)
    publish_to_job_stream(job_id, {"event": "new", "job_id": job_id})
    publish_to_global_stream({"event": "new", "job_id": job_id})


async def patched_publish_progress(
    redis, job_id: str, percent: int, stage: str, message: str
) -> None:
    """Publish progress and also to SSE streams."""
    await _original_publish_progress(redis, job_id, percent, stage, message)
    publish_to_job_stream(
        job_id,
        {"event": "progress", "job_id": job_id, "percent": percent, "stage": stage, "message": message},
    )
    publish_to_global_stream(
        {"event": "progress", "job_id": job_id, "percent": percent, "stage": stage, "message": message}
    )


async def patched_publish_cancel(redis, job_id: str) -> None:
    """Publish cancel and also to SSE streams."""
    await _original_publish_cancel(redis, job_id)
    publish_to_job_stream(job_id, {"event": "cancel", "job_id": job_id})
    publish_to_global_stream({"event": "cancel", "job_id": job_id})


async def patched_publish_done(
    redis, job_id: str, status: str, error: str | None = None
) -> None:
    """Publish done and also to SSE streams."""
    await _original_publish_done(redis, job_id, status, error)
    payload = {"event": "done", "job_id": job_id, "status": status}
    if error:
        payload["error"] = error
    publish_to_job_stream(job_id, payload)
    publish_to_global_stream(payload)


# Apply patches
events_module.publish_new = patched_publish_new
events_module.publish_progress = patched_publish_progress
events_module.publish_cancel = patched_publish_cancel
events_module.publish_done = patched_publish_done
