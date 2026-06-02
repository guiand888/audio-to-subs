"""SSE routes for job progress streaming."""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Annotated, Any, AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from audio_to_subs.api.deps import SettingsDep, get_db
from audio_to_subs.api.settings import Settings
from audio_to_subs.db.models import Job, JobStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["stream"])

# Global event queue for fan-out
# This maps job_id -> asyncio.Queue for per-job events
_job_event_queues: dict[str, asyncio.Queue] = {}
_global_event_queue: asyncio.Queue | None = None


def _get_job_queue(job_id: str) -> asyncio.Queue:
    """Get or create an event queue for a job."""
    global _job_event_queues
    if job_id not in _job_event_queues:
        _job_event_queues[job_id] = asyncio.Queue()
    return _job_event_queues[job_id]


def _get_global_queue() -> asyncio.Queue:
    """Get or create the global event queue."""
    global _global_event_queue
    if _global_event_queue is None:
        _global_event_queue = asyncio.Queue()
    return _global_event_queue


async def _event_generator(
    job_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Generate SSE events for a job or globally.

    Args:
        job_id: Specific job ID to stream, or None for global stream
    """
    if job_id:
        queue = _get_job_queue(job_id)
    else:
        queue = _get_global_queue()

    try:
        while True:
            event_data = await queue.get()
            yield f"data: {json.dumps(event_data)}\n\n"
    except asyncio.CancelledError:
        logger.debug(f"SSE connection cancelled for job {job_id}")
    except Exception as e:
        logger.error(f"SSE error for job {job_id}: {e}")
    finally:
        # Clean up if this was the last listener
        if job_id and job_id in _job_event_queues:
            del _job_event_queues[job_id]


@router.get("/stream")
async def global_stream(
    request: Request,
    settings: Settings = Depends(SettingsDep),
) -> EventSourceResponse:
    """Global SSE stream for all job events.

    Returns a Server-Sent Events stream that receives notifications for all
    job lifecycle events (new, progress, cancel, done).
    """
    return EventSourceResponse(
        _event_generator(None),
        media_type="text/event-stream",
    )


@router.get("/{job_id}/stream")
async def job_stream(
    job_id: UUID,
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    settings: Settings = Depends(SettingsDep),
) -> EventSourceResponse:
    """Per-job SSE stream for progress updates.

    Returns a Server-Sent Events stream that receives notifications for
    the specific job's progress and completion events.
    """
    # Verify job exists
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    return EventSourceResponse(
        _event_generator(str(job_id)),
        media_type="text/event-stream",
    )


# Functions to publish events to SSE streams
def publish_to_job_stream(job_id: str, event_data: dict[str, Any]) -> None:
    """Publish an event to a job-specific SSE stream.

    Args:
        job_id: Job ID to publish to
        event_data: Event data as dict
    """
    queue = _get_job_queue(job_id)
    queue.put_nowait(event_data)


def publish_to_global_stream(event_data: dict[str, Any]) -> None:
    """Publish an event to the global SSE stream.

    Args:
        event_data: Event data as dict
    """
    queue = _get_global_queue()
    queue.put_nowait(event_data)


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
