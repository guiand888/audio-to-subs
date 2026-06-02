"""Job routes for managing transcription jobs."""

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.orm import joinedload

from audio_to_subs.api.deps import SettingsDep, get_db
from audio_to_subs.api.settings import Settings
from audio_to_subs.db.models import (
    Job,
    JobStatus,
    JobSource,
    JobLog,
    OutputFormat,
    LogLevel,
)
from audio_to_subs.queue_.events import publish_new, publish_cancel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# Request/Response models
class JobCreateRequest(BaseModel):
    """Request body for creating a new job."""

    source: JobSource = Field(..., description="Job source: manual, bazarr_movie, bazarr_episode")
    source_ref: str | None = Field(
        default=None,
        description="Reference to external source (e.g., Bazarr ID)",
    )
    media_path: str = Field(..., description="Path to the media file to process")
    output_path: str | None = Field(
        default=None,
        description="Path where output subtitles should be written (auto-generated if not provided)",
    )
    language_code: str | None = Field(
        default=None,
        description="Language code for transcription (e.g., 'en', 'fr')",
    )
    output_format: OutputFormat = Field(
        default=OutputFormat.SRT,
        description="Output subtitle format",
    )
    priority: int = Field(
        default=0,
        ge=0,
        description="Job priority (higher = processed first)",
    )


class JobResponse(BaseModel):
    """Response model for a job."""

    id: UUID
    status: JobStatus
    source: JobSource
    source_ref: str | None
    media_path: str
    output_path: str | None
    language_code: str | None
    output_format: OutputFormat
    priority: int
    progress_percent: int
    progress_message: str | None
    cancel_requested: bool
    worker_id: str | None
    audio_duration_seconds: float | None
    mistral_usage_json: str | None
    estimated_cost_usd: float | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    """Response model for job list."""

    jobs: list[JobResponse]
    total: int
    queued: int
    running: int
    done: int
    failed: int
    cancelled: int


class JobStatsResponse(BaseModel):
    """Response model for job statistics."""

    total: int
    queued: int
    running: int
    done: int
    failed: int
    cancelled: int


@router.get("", response_model=JobListResponse)
async def list_jobs(
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    status_filter: JobStatus | None = None,
    source_filter: JobSource | None = None,
    limit: int = 100,
    offset: int = 0,
) -> JobListResponse:
    """List all jobs with optional filtering.

    Returns a paginated list of jobs with counts by status.
    """
    # Build query
    query = select(Job)

    # Apply filters
    conditions = []
    if status_filter is not None:
        conditions.append(Job.status == status_filter)
    if source_filter is not None:
        conditions.append(Job.source == source_filter)

    if conditions:
        query = query.where(and_(*conditions))

    # Count by status for summary
    from sqlalchemy import case, cast, Integer

    status_counts = (
        await db.execute(
            select(
                Job.status,
                func.count(Job.id).label("count"),
            )
            .group_by(Job.status)
        )
    ).all()

    counts = {status: 0 for status in JobStatus}
    for row in status_counts:
        if row[0] in counts:
            counts[row[0]] = row[1]

    # Get paginated jobs
    query = query.order_by(desc(Job.created_at)).limit(limit).offset(offset)
    result = await db.execute(query)
    jobs = result.scalars().all()

    return JobListResponse(
        jobs=[JobResponse.model_validate(job) for job in jobs],
        total=len(jobs),
        queued=counts[JobStatus.QUEUED],
        running=counts[JobStatus.RUNNING],
        done=counts[JobStatus.DONE],
        failed=counts[JobStatus.FAILED],
        cancelled=counts[JobStatus.CANCELLED],
    )


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    settings: Settings = Depends(SettingsDep),
    job_request: JobCreateRequest = ...,  # type: ignore
) -> JobResponse:
    """Create a new transcription job.

    Creates a job in 'queued' state and publishes a new job notification
    to Redis for workers to pick up.
    """
    # Validate media_path for path traversal
    import os

    media_path = job_request.media_path
    if ".." in media_path or media_path.startswith("/"):
        # Resolve to absolute path and check it's within allowed directories
        resolved = os.path.abspath(media_path)
        # For now, we allow any path but log a warning
        logger = logging.getLogger(__name__)
        logger.warning(f"Potential path traversal in media_path: {media_path}")

    # Create job
    job = Job(
        id=uuid4(),
        status=JobStatus.QUEUED,
        source=job_request.source,
        source_ref=job_request.source_ref,
        media_path=job_request.media_path,
        output_path=job_request.output_path,
        language_code=job_request.language_code,
        output_format=job_request.output_format,
        priority=job_request.priority,
        progress_percent=0,
        progress_message="Job created, waiting for worker",
        cancel_requested=False,
    )

    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Publish new job notification
    try:
        redis = None
        if settings.REDIS_URL:
            import redis.asyncio as redis_lib

            redis = redis_lib.from_url(settings.REDIS_URL)
            await publish_new(redis, str(job.id))
            await redis.close()
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to publish new job: {e}")

    return JobResponse.model_validate(job)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    db: Annotated["AsyncSession", Depends(get_db)],
) -> JobResponse:
    """Get details for a specific job."""
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    return JobResponse.model_validate(job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: UUID,
    db: Annotated["AsyncSession", Depends(get_db)],
    settings: Settings = Depends(SettingsDep),
) -> JobResponse:
    """Request cancellation of a job.

    Sets cancel_requested flag and publishes cancellation notification.
    The worker will pick this up and terminate the pipeline.
    
    If the job is still queued, it will be marked as cancelled immediately.
    """
    from sqlalchemy import text

    # Get current job state
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # If job is still queued, cancel it immediately
    if job.status == JobStatus.QUEUED:
        update_stmt = text(
            "UPDATE jobs SET status='cancelled', finished_at=CURRENT_TIMESTAMP, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=:job_id"
        )
        await db.execute(update_stmt, {"job_id": str(job_id)})
        await db.commit()

        # Publish cancel event
        try:
            redis = None
            if settings.REDIS_URL:
                import redis.asyncio as redis_lib

                redis = redis_lib.from_url(settings.REDIS_URL)
                await publish_cancel(redis, str(job_id))
                await redis.close()
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to publish cancel: {e}")

        # Refresh job
        await db.refresh(job)
        return JobResponse.model_validate(job)

    # If job is running, set cancel_requested flag
    elif job.status == JobStatus.RUNNING:
        update_stmt = text(
            "UPDATE jobs SET cancel_requested=1, updated_at=CURRENT_TIMESTAMP WHERE id=:job_id"
        )
        await db.execute(update_stmt, {"job_id": str(job_id)})
        await db.commit()

        # Publish cancel event
        try:
            redis = None
            if settings.REDIS_URL:
                import redis.asyncio as redis_lib

                redis = redis_lib.from_url(settings.REDIS_URL)
                await publish_cancel(redis, str(job_id))
                await redis.close()
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to publish cancel: {e}")

        # Refresh job
        await db.refresh(job)
        return JobResponse.model_validate(job)

    # If job is already terminal, just return it
    elif job.is_terminal:
        return JobResponse.model_validate(job)

    # For other states, still try to set cancel_requested
    else:
        update_stmt = text(
            "UPDATE jobs SET cancel_requested=1, updated_at=CURRENT_TIMESTAMP WHERE id=:job_id"
        )
        await db.execute(update_stmt, {"job_id": str(job_id)})
        await db.commit()
        await db.refresh(job)
        return JobResponse.model_validate(job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: UUID,
    db: Annotated["AsyncSession", Depends(get_db)],
) -> None:
    """Delete a job.

    Only allows deletion of queued jobs. Jobs that are running or completed
    cannot be deleted (they have audit value).
    """
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    if job.status != JobStatus.QUEUED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete job in {job.status} state",
        )

    await db.delete(job)
    await db.commit()


# Import logging for use in functions
import logging
logger = logging.getLogger(__name__)
