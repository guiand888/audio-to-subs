"""Job routes for managing transcription jobs."""

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.orm import joinedload

from audio_to_subs.api.deps import SettingsDep, get_db
from audio_to_subs.api.routes._helpers import get_job_or_404, publish_job_event
from audio_to_subs.bazarr.pathmap import PathMap
from audio_to_subs.core.path_utils import generate_output_path, validate_media_path
from audio_to_subs.db.models import (
    BazarrCache,
    Job,
    JobStatus,
    JobSource,
    JobLog,
    OutputFormat,
    LogLevel,
    Setting,
)
from audio_to_subs.queue_.events import publish_new, publish_cancel

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
    from sqlalchemy import case, cast, Integer

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


async def _get_path_map(db: "AsyncSession") -> PathMap:
    """Get PathMap from database settings."""
    return await PathMap.load_from_db(db)


async def _resolve_bazarr_source(
    db: "AsyncSession",
    source: JobSource,
    source_ref: str | None,
    requested_media_path: str | None,
    path_map: PathMap,
) -> tuple[str, str | None]:
    """Resolve Bazarr source to media path.

    Args:
        db: Database session
        source: Job source
        source_ref: Reference ID (e.g., Radarr or Sonarr ID)
        requested_media_path: Optional requested media path (for manual override)
        path_map: PathMap for path translation

    Returns:
        Tuple of (media_path, source_ref)

    Raises:
        HTTPException: If source is bazarr but source_ref not found in cache
    """
    logger = logging.getLogger(__name__)

    if source in (JobSource.BAZARR_MOVIE, JobSource.BAZARR_EPISODE):
        if source_ref is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"source_ref is required for source={source.value}",
            )

        # Look up in bazarr_cache
        cache_id = BazarrCache.make_id(
            "movie" if source == JobSource.BAZARR_MOVIE else "episode",
            int(source_ref),
        )

        result = await db.execute(select(BazarrCache).where(BazarrCache.id == cache_id))
        cache_entry = result.scalar_one_or_none()

        if cache_entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Bazarr item {cache_id} not found in cache. "
                "Please ensure Bazarr poller has run and the item exists.",
            )

        # Use the cached media_path (already translated by poller)
        media_path = cache_entry.media_path

        # If requested_media_path is provided, use it (allows override)
        if requested_media_path:
            media_path = path_map.translate(requested_media_path)
            logger.info(
                "Using requested media_path override for %s: %s",
                cache_id,
                media_path,
            )

        return media_path, source_ref

    else:
        # Manual source - use provided media_path
        if requested_media_path is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="media_path is required for manual source",
            )
        return requested_media_path, source_ref


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
    logger = logging.getLogger(__name__)

    # Get path map for path translation
    path_map = await _get_path_map(db)

    # Resolve media_path based on source
    try:
        media_path, resolved_source_ref = await _resolve_bazarr_source(
            db,
            job_request.source,
            job_request.source_ref,
            job_request.media_path,
            path_map,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to resolve Bazarr source: %s", e)
        logger.error(f"Failed to resolve source: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to resolve source. Please check your source configuration.",
        )

    # Validate media_path against configured root paths (handles symlinks and traversal)
    movies_root = getattr(settings, "MOVIES_ROOT_PATH", None)
    tv_root = getattr(settings, "TV_ROOT_PATH", None)

    is_valid, error_msg = validate_media_path(media_path, movies_root, tv_root)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid media path: {error_msg}",
        )

    # Auto-generate output_path if not provided and subtitles_same_directory is enabled
    subtitles_same_dir = getattr(settings, "SUBTITLES_SAME_DIRECTORY", True)
    output_path = job_request.output_path
    if not output_path and subtitles_same_dir:
        output_path = generate_output_path(
            media_path,
            job_request.language_code,
            job_request.output_format,
            subtitles_same_dir,
        )
    elif output_path:
        # Validate provided output_path is within safe directory
        is_valid, error_msg = validate_media_path(output_path, movies_root, tv_root)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid output path: {error_msg}",
            )

    # Use resolved source_ref
    source_ref = resolved_source_ref or job_request.source_ref

    # Apply defaults from settings if not provided
    language_code = job_request.language_code
    output_format = job_request.output_format

    # Try to get defaults from settings
    if language_code is None:
        try:
            result = await db.execute(
                select(Setting.value_json).where(Setting.key == "default_language")
            )
            row = result.scalar_one_or_none()
            if row and row.value_json:
                import json

                language_code = json.loads(row.value_json)
        except Exception:
            pass

    # Try to get default output format from settings
    if output_format == OutputFormat.SRT:
        # Only override if there's a different default
        try:
            result = await db.execute(
                select(Setting.value_json).where(Setting.key == "default_output_format")
            )
            row = result.scalar_one_or_none()
            if row and row.value_json:
                import json

                default_format = json.loads(row.value_json)
                if default_format and default_format != "srt":
                    try:
                        output_format = OutputFormat(default_format)
                    except ValueError:
                        pass  # Invalid format, keep default
        except Exception:
            pass

    # Create job
    job = Job(
        id=uuid4(),
        status=JobStatus.QUEUED,
        source=job_request.source,
        source_ref=source_ref,
        media_path=media_path,
        output_path=output_path,
        language_code=language_code,
        output_format=output_format,
        priority=job_request.priority,
        progress_percent=0,
        progress_message="Job created, waiting for worker",
        cancel_requested=False,
    )

    db.add(job)
    await db.commit()
    await db.refresh(job)

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
    from sqlalchemy import text

    # Get current job state
    job = await get_job_or_404(db, job_id)

    # If job is still queued, cancel it immediately
    if job.status == JobStatus.QUEUED:
        update_stmt = text(
            "UPDATE jobs SET status='cancelled', finished_at=CURRENT_TIMESTAMP, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=:job_id"
        )
        await db.execute(update_stmt, {"job_id": str(job_id)})
        await db.commit()

        await publish_job_event(settings, publish_cancel, str(job_id), "cancel")

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

        await publish_job_event(settings, publish_cancel, str(job_id), "cancel")

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
    job = await get_job_or_404(db, job_id)

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
    logger = logging.getLogger(__name__)

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
    if job.source == JobSource.BAZARR_MOVIE:
        logger.info(f"Triggering Bazarr rescan for movie job {job_id}")
        try:
            if job.source_ref:
                radarr_id = int(job.source_ref)
                await client.rescan_movie(radarr_id)
                logger.info(f"Triggered Bazarr rescan for movie {radarr_id}")

            await client.close()
            return {
                "status": "triggered",
                "source": "bazarr_movie",
                "source_ref": job.source_ref,
            }

        except Exception as e:
            logger.warning(f"Failed to trigger Bazarr rescan for job {job_id}: {e}")
            await client.close()
            return {"status": "failed", "error": str(e)}

    elif job.source == JobSource.BAZARR_EPISODE:
        logger.info(f"Triggering Bazarr rescan for episode job {job_id}")
        try:
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
                        await client.close()
                        return {"status": "failed", "error": "Bazarr rescan failed"}
                    logger.info(
                        f"Triggered Bazarr rescan for episode {sonarr_episode_id}"
                    )
                else:
                    logger.warning(
                        f"Cannot trigger Bazarr rescan for episode {sonarr_episode_id}: "
                        "episode not found in Bazarr"
                    )
                    await client.close()
                    return {"status": "failed", "error": "episode not found in Bazarr"}

            await client.close()
            return {
                "status": "triggered",
                "source": "bazarr_episode",
                "source_ref": job.source_ref,
            }

        except Exception as e:
            logger.warning(f"Failed to trigger Bazarr rescan for job {job_id}: {e}")
            await client.close()
            return {"status": "failed", "error": str(e)}

    else:
        # Unknown Bazarr source type — shouldn't happen given the enum, but guard it
        logger.warning(f"Unhandled source {job.source!r} for job {job_id}")
        await client.close()
        return {"status": "skipped", "reason": f"Unhandled source: {job.source}"}
