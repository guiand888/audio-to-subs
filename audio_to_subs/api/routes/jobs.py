"""Job routes for managing transcription jobs."""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select

from audio_to_subs.api.deps import SettingsDep, get_db
from audio_to_subs.api.routes._helpers import get_job_or_404, publish_job_event
from audio_to_subs.api.services.jobs import create_job_service
from audio_to_subs.core.file_rename import rename_subtitle_language
from audio_to_subs.db.models import (
    Job,
    JobSource,
    JobStatus,
    OutputFormat,
)
from audio_to_subs.queue_.events import publish_cancel, publish_new

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# Request/Response models
class JobCreateRequest(BaseModel):
    """Request body for creating a new job."""

    source: JobSource = Field(
        ..., description="Job source: manual, bazarr_movie, bazarr_episode"
    )
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
    language_mode: Literal["auto", "explicit"] = Field(
        default="explicit",
        description=(
            "'auto' lets Mistral auto-detect the audio language and ignores "
            "language_code; 'explicit' uses language_code as given"
        ),
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

    model_config = {"from_attributes": True}

    id: UUID
    status: JobStatus
    source: JobSource
    source_ref: str | None
    media_path: str
    output_path: str | None
    language_code: str | None
    language_mode: str
    mistral_detected_language: str | None
    needs_language_review: bool
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

    # Count total matching jobs (respecting filters)
    count_query = select(func.count(Job.id)).select_from(Job)
    if conditions:
        count_query = count_query.where(and_(*conditions))
    total_count = (await db.execute(count_query)).scalar() or 0

    # Count by status for summary (also respecting filters)
    status_counts = (
        await db.execute(
            select(
                Job.status,
                func.count(Job.id).label("count"),
            )
            .select_from(Job)
            .where(and_(*conditions) if conditions else True)
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
        total=total_count,
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
    settings: SettingsDep,
    job_request: JobCreateRequest = ...,  # type: ignore
) -> JobResponse:
    """Create a new transcription job.

    Creates a job in 'queued' state and publishes a new job notification
    to Redis for workers to pick up.

    For bazarr_movie/bazarr_episode sources, resolves media_path from cache.
    """
    # Create job via service
    job = await create_job_service(
        db=db,
        settings=settings,
        source=job_request.source,
        source_ref=job_request.source_ref,
        media_path=job_request.media_path,
        output_path=job_request.output_path,
        language_code=job_request.language_code,
        language_mode=job_request.language_mode,
        output_format=job_request.output_format,
        priority=job_request.priority,
    )

    # Publish new job notification
    await publish_job_event(settings, publish_new, str(job.id), "new job")

    return JobResponse.model_validate(job)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    db: Annotated["AsyncSession", Depends(get_db)],
) -> JobResponse:
    """Get details for a specific job."""
    job = await get_job_or_404(db, job_id)

    return JobResponse.model_validate(job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: UUID,
    db: Annotated["AsyncSession", Depends(get_db)],
    settings: SettingsDep,
) -> JobResponse:
    """Request cancellation of a job.

    Sets cancel_requested flag and publishes cancellation notification.
    The worker will pick this up and terminate the pipeline.

    If the job is still queued, it will be marked as cancelled immediately.
    """
    # Get current job state
    job = await get_job_or_404(db, job_id)

    # If job is still queued, cancel it immediately
    if job.status == JobStatus.QUEUED:
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()

        await publish_job_event(settings, publish_cancel, str(job_id), "cancel")

        await db.refresh(job)
        return JobResponse.model_validate(job)

    # If job is running, set cancel_requested flag
    elif job.status == JobStatus.RUNNING:
        job.cancel_requested = True
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()

        await publish_job_event(settings, publish_cancel, str(job_id), "cancel")

        await db.refresh(job)
        return JobResponse.model_validate(job)

    # If job is already terminal, just return it
    elif job.is_terminal:
        return JobResponse.model_validate(job)

    # For other states, still try to set cancel_requested
    else:
        job.cancel_requested = True
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(job)
        return JobResponse.model_validate(job)


class JobLanguagePatchRequest(BaseModel):
    """Request body for correcting a completed job's language."""

    language_code: str = Field(
        ..., min_length=2, max_length=3, description="New ISO 639-1/2 language code"
    )


@router.patch("/{job_id}/language", response_model=JobResponse)
async def update_job_language(
    job_id: UUID,
    db: Annotated["AsyncSession", Depends(get_db)],
    patch: JobLanguagePatchRequest,
) -> JobResponse:
    """Correct a completed job's language after the fact.

    Renames the on-disk output file to the new language suffix and clears
    needs_language_review. Only valid for DONE jobs that have an output_path.
    """
    job = await get_job_or_404(db, job_id)

    if job.status != JobStatus.DONE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only correct language for completed jobs",
        )
    if not job.output_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job has no output file to rename",
        )

    new_code = patch.language_code.lower().strip()
    if not (2 <= len(new_code) <= 3 and new_code.isalpha()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid language code",
        )

    new_path = rename_subtitle_language(job.output_path, job.language_code, new_code)

    job.output_path = new_path
    job.language_code = new_code
    job.needs_language_review = False
    job.updated_at = datetime.now(timezone.utc)
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
    job = await get_job_or_404(db, job_id)

    if job.status != JobStatus.QUEUED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete job in {job.status} state",
        )

    await db.delete(job)
    await db.commit()


logger = logging.getLogger(__name__)


@router.post("/{job_id}/notify-bazarr", status_code=status.HTTP_202_ACCEPTED)
async def notify_bazarr(
    job_id: UUID,
    db: Annotated["AsyncSession", Depends(get_db)],
    settings: SettingsDep,
) -> dict[str, str]:
    """Trigger Bazarr rescan for a completed job.

    This endpoint triggers a rescan in Bazarr for the source media of a job.
    It's a best-effort operation that runs asynchronously.

    For bazarr_movie jobs: triggers rescan for the Radarr movie
    For bazarr_episode jobs: triggers rescan for the Sonarr episode
    For manual jobs: returns 202 without action (no Bazarr source)

    Uses database settings first, falling back to environment variables.

    Returns 202 Accepted in all cases - the rescan is best-effort.
    """
    # Get the job
    job = await get_job_or_404(db, job_id)

    # Skip manual jobs immediately — Bazarr config is irrelevant for them.
    if job.source not in (JobSource.BAZARR_MOVIE, JobSource.BAZARR_EPISODE):
        logger.info(f"Job {job_id} is manual source, skipping Bazarr rescan")
        return {"status": "skipped", "reason": "Manual job has no Bazarr source"}

    # Get Bazarr client using database settings first, then environment fallback
    from audio_to_subs.bazarr.poller import get_bazarr_client_with_settings

    client, bazarr_url, bazarr_api_key, bazarr_timeout = (
        await get_bazarr_client_with_settings(db, settings)
    )

    if client is None:
        logger.info(
            f"Bazarr not configured (URL or API key missing), "
            f"skipping rescan for job {job_id}"
        )
        return {"status": "skipped", "reason": "Bazarr not configured"}

    # Trigger rescan for Bazarr-sourced jobs
    try:
        if job.source == JobSource.BAZARR_MOVIE:
            logger.info(f"Triggering Bazarr rescan for movie job {job_id}")
            if job.source_ref:
                radarr_id = int(job.source_ref)
                await client.rescan_movie(radarr_id)
                logger.info(f"Triggered Bazarr rescan for movie {radarr_id}")

            return {
                "status": "triggered",
                "source": "bazarr_movie",
                "source_ref": job.source_ref,
            }

        elif job.source == JobSource.BAZARR_EPISODE:
            logger.info(f"Triggering Bazarr rescan for episode job {job_id}")
            if job.source_ref:
                sonarr_episode_id = int(job.source_ref)
                # Fetch series_id from Bazarr since rescan_episode requires it
                # (Bazarr only supports series-level scan, not per-episode)
                episode = await client.get_episode(sonarr_episode_id)
                if episode:
                    success = await client.rescan_episode(
                        sonarr_episode_id, series_id=episode.sonarrSeriesId
                    )
                    if not success:
                        logger.warning(
                            f"Bazarr rescan failed for episode {sonarr_episode_id}"
                        )
                        return {"status": "failed", "error": "Bazarr rescan failed"}
                    logger.info(
                        f"Triggered Bazarr rescan for episode {sonarr_episode_id}"
                    )
                else:
                    logger.warning(
                        f"Cannot trigger Bazarr rescan for episode {sonarr_episode_id}: "
                        "episode not found in Bazarr"
                    )
                    return {"status": "failed", "error": "episode not found in Bazarr"}

            return {
                "status": "triggered",
                "source": "bazarr_episode",
                "source_ref": job.source_ref,
            }

        else:
            # Unknown Bazarr source type — shouldn't happen given the enum, but guard it
            logger.warning(f"Unhandled source {job.source!r} for job {job_id}")
            return {"status": "skipped", "reason": f"Unhandled source: {job.source}"}

    except Exception as e:
        logger.warning(f"Failed to trigger Bazarr rescan for job {job_id}: {e}")
        return {"status": "failed", "error": str(e)}

    finally:
        await client.close()
