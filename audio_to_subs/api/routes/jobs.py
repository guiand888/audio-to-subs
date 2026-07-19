"""Job routes for managing transcription jobs."""

import logging
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy import and_, desc, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from audio_to_subs.api.deps import SettingsDep, get_db, get_redis
from audio_to_subs.api.routes._helpers import (
    UTCAwareModel,
    get_job_or_404,
    publish_job_event,
)
from audio_to_subs.api.services.jobs import create_job_service
from audio_to_subs.core.file_rename import (
    compute_rename_target,
    rename_subtitle_language,
)
from audio_to_subs.db.job_logs import write_job_log
from audio_to_subs.db.models import (
    Job,
    JobSource,
    JobStatus,
    LogLevel,
    OutputFormat,
)
from audio_to_subs.queue_.events import (
    get_job_progress,
    publish_cancel,
    publish_new,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# Request/Response models
class JobCreateRequest(BaseModel):
    """Request body for creating a new job."""

    source: JobSource = Field(
        ..., description="Job source: manual, bazarr_movie, bazarr_episode"
    )

    @field_validator("media_path", "output_path")
    @classmethod
    def _validate_path_fields(cls, v: str | None) -> str | None:
        """Early rejection of malformed paths at the request boundary.

        Root containment is enforced later in ``create_job_service`` (which has
        access to configured roots), but control characters, NUL bytes, and
        relative paths are rejected here so they never reach the service layer.

        Empty strings are passed through: an empty ``media_path`` is a valid
        signal for a Bazarr source without a resolvable file, and the service
        layer returns a clearer, source-specific error for it.
        """
        if v is None or v == "":
            return v
        if "\x00" in v or re.search(r"[\x00-\x1f\x7f]", v):
            raise ValueError("path contains invalid control characters")
        if not os.path.isabs(v):
            raise ValueError("path must be absolute")
        return v

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
    overwrite: bool = Field(
        default=False,
        description=(
            "When True, allow the worker to replace an existing output "
            "subtitle if one already exists (M6.g overwrite guard)."
        ),
    )


class JobResponse(UTCAwareModel):
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
    # Progress is no longer stored in the DB; it is supplied by the Redis
    # live-progress overlay (non-terminal jobs) or derived from status
    # (terminal jobs). Defaults keep the response valid when neither applies.
    progress_percent: int = 0
    progress_message: str | None = None
    # M5.8 (#4, verified): persisted step/stage for step-based UX + refresh
    # survival. Nullable; step_index/step_total are None until extracted.
    progress_stage: str | None = None
    progress_step_index: int | None = None
    progress_step_total: int | None = None
    cancel_requested: bool
    worker_id: str | None
    audio_duration_seconds: float | None
    runtime_seconds: float | None = None
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


async def _overlay_live_progress(
    redis: Redis, jobs: Sequence[Any]
) -> dict[str, dict[str, Any]]:
    """Build live-progress overrides for non-terminal jobs from Redis.

    For each job that is not in a terminal state, read its
    ``job:progress:{id}`` hash (via the shared ``get_job_progress`` helper) and
    return a dict keyed by job id whose value is the live
    ``progress_percent``/``progress_message``/``progress_stage``/
    ``progress_step_index``/``progress_step_total`` to overlay onto the
    serialized ``JobResponse``. Terminal jobs are skipped (their Redis key was
    cleared on completion, and their progress is inferred from status).

    Best-effort and per-job isolated: a Redis error or malformed snapshot for
    one job yields no override for *that* job only, so the caller falls back to
    the terminal-status-derived default for it; other jobs are unaffected.
    """
    overrides: dict[str, dict[str, Any]] = {}
    live = [job for job in jobs if not getattr(job, "is_terminal", False)]
    if not live:
        return overrides
    for job in live:
        snap = await get_job_progress(redis, str(job.id))
        if not snap:
            continue
        # Per-job isolation: a malformed snapshot must not drop overrides for
        # the rest of the batch (previous versions wrapped the whole pipeline
        # in one try/except and lost every job on a single failure).
        try:
            override: dict[str, Any] = {}

            pct = snap.get("percent")
            if pct:
                try:
                    override["progress_percent"] = int(pct)
                except (ValueError, TypeError):
                    pass

            stage = snap.get("stage")
            if stage:
                override["progress_stage"] = stage

            msg = snap.get("message")
            override["progress_message"] = msg if msg else None

            si = snap.get("step_index")
            override["progress_step_index"] = _safe_int(si)
            st = snap.get("step_total")
            override["progress_step_total"] = _safe_int(st)
        except (ValueError, TypeError) as e:  # noqa: BLE001
            logger.error(f"Malformed progress snapshot for job {job.id}: {e}")
            continue

        if override:
            overrides[str(job.id)] = override
    return overrides


def _safe_int(value: object) -> int | None:
    """Parse an optional step index/total to int, returning None on bad input.

    ``step_index``/``step_total`` are stored as strings in the Redis hash; a
    corrupt value must degrade to ``None`` (no step UI) rather than raise.
    """
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return None


def _terminal_progress(status: JobStatus) -> int:
    """Progress percent for a terminal job, derived from status.

    ``done`` ⇒ 100; ``failed``/``cancelled`` ⇒ 0. Used because the DB no
    longer stores a progress column; the live Redis snapshot is cleared when a
    job reaches a terminal state.
    """
    return 100 if status == JobStatus.DONE else 0


def _to_job_response(job: Any, progress_overrides: Mapping[str, Any]) -> JobResponse:
    """Build a JobResponse, applying the Redis live-progress overlay.

    Terminal jobs have no Redis snapshot, so their progress is derived from
    status (done ⇒ 100, otherwise 0). Non-terminal jobs adopt the live
    override when present.
    """
    resp = JobResponse.model_validate(job)
    if getattr(job, "is_terminal", False):
        resp.progress_percent = _terminal_progress(job.status)
        resp.progress_message = None
        resp.progress_stage = None
        resp.progress_step_index = None
        resp.progress_step_total = None
    override = progress_overrides.get(str(job.id))
    if override:
        for key, value in override.items():
            setattr(resp, key, value)
    return resp


@router.get("", response_model=JobListResponse)
async def list_jobs(
    request: Request,
    db: Annotated["AsyncSession", Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
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
            .where(and_(*conditions) if conditions else true())
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

    # Overlay fresh live progress from Redis onto non-terminal jobs. In-flight
    # progress lives in Redis (the worker no longer writes it to the DB); the
    # DB has no progress columns. This makes polling see fresh progress
    # immediately instead of waiting for a debounced write. Best-effort: any
    # Redis failure degrades to the terminal-status-derived default.
    progress_overrides = await _overlay_live_progress(redis, jobs)

    return JobListResponse(
        jobs=[_to_job_response(job, progress_overrides) for job in jobs],
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
    # Required request body. ``Annotated[JobCreateRequest, Body()]`` replaces the
    # previous ``job_request: JobCreateRequest = ...`` idiom, which needed a
    # ``# type: ignore`` under mypy --strict because ``...`` is not a
    # ``JobCreateRequest`` (M5.7). ``Body()`` with no default marks it required,
    # identical to the old behavior but type-clean.
    job_request: Annotated[JobCreateRequest, Body()],
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
        overwrite=job_request.overwrite,
    )

    # Publish new job notification
    await publish_job_event(settings, publish_new, str(job.id), "new job")

    return JobResponse.model_validate(job)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    db: Annotated["AsyncSession", Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> JobResponse:
    """Get details for a specific job."""
    job = await get_job_or_404(db, job_id)

    # Apply the same live-progress overlay + terminal derivation as list_jobs.
    progress_overrides = await _overlay_live_progress(redis, [job])
    return _to_job_response(job, progress_overrides)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: UUID,
    db: Annotated["AsyncSession", Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
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
        return _to_job_response(job, {})

    # If job is running, set cancel_requested flag. Reply with the live
    # progress overlay so the client sees the in-flight percent/message, not 0.
    elif job.status == JobStatus.RUNNING:
        job.cancel_requested = True
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()

        await publish_job_event(settings, publish_cancel, str(job_id), "cancel")

        await db.refresh(job)
        progress_overrides = await _overlay_live_progress(redis, [job])
        return _to_job_response(job, progress_overrides)

    # If job is already terminal, derive progress from status (done => 100).
    elif job.is_terminal:
        return _to_job_response(job, {})

    # For other states, still try to set cancel_requested
    else:
        job.cancel_requested = True
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(job)
        progress_overrides = await _overlay_live_progress(redis, [job])
        return _to_job_response(job, progress_overrides)


class JobLanguagePatchRequest(BaseModel):
    """Request body for correcting a completed job's language."""

    language_code: str = Field(
        ..., min_length=2, max_length=3, description="New ISO 639-1/2 language code"
    )
    overwrite: bool = Field(
        default=False,
        description=(
            "When True, allow renaming onto an existing output file instead "
            "of refusing with a 409 subtitle_exists (M6.g overwrite guard)."
        ),
    )


@router.patch("/{job_id}/language", response_model=JobResponse)
async def update_job_language(
    job_id: UUID,
    db: Annotated["AsyncSession", Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
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

    # M6.g language-correction rename guard: compute the target path WITHOUT
    # renaming first, and check for an existing file strictly BEFORE the rename
    # (which would otherwise replace the destination silently). Refuse with 409
    # subtitle_exists unless the caller explicitly opted into overwrite.
    new_path = compute_rename_target(job.output_path, job.language_code, new_code)
    if not patch.overwrite and os.path.exists(new_path):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "subtitle_exists",
                "message": (f"A subtitle already exists at the target path {new_path}"),
                "existing_path": new_path,
                "language_code": new_code,
            },
        )

    new_path = rename_subtitle_language(job.output_path, job.language_code, new_code)
    job.output_path = new_path
    job.language_code = new_code
    job.needs_language_review = False
    job.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(job)

    # DONE job => terminal progress derivation (100). No live overlay applies.
    return _to_job_response(job, {})


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
) -> dict[str, str | None]:
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
                await write_job_log(
                    db,
                    LogLevel.INFO,
                    f"Triggered Bazarr rescan for movie {radarr_id}",
                    job_id=job_id,
                )

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
                        await write_job_log(
                            db,
                            LogLevel.WARNING,
                            f"Bazarr rescan failed for episode {sonarr_episode_id}",
                            job_id=job_id,
                        )
                        return {"status": "failed", "error": "Bazarr rescan failed"}
                    logger.info(
                        f"Triggered Bazarr rescan for episode {sonarr_episode_id}"
                    )
                    await write_job_log(
                        db,
                        LogLevel.INFO,
                        f"Triggered Bazarr rescan for episode {sonarr_episode_id}",
                        job_id=job_id,
                    )
                else:
                    logger.warning(
                        f"Cannot trigger Bazarr rescan for episode {sonarr_episode_id}: "
                        "episode not found in Bazarr"
                    )
                    await write_job_log(
                        db,
                        LogLevel.WARNING,
                        f"Cannot trigger Bazarr rescan for episode "
                        f"{sonarr_episode_id}: episode not found in Bazarr",
                        job_id=job_id,
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
            await write_job_log(
                db,
                LogLevel.WARNING,
                f"Unhandled Bazarr source {job.source!r} for job {job_id}",
                job_id=job_id,
            )
            return {"status": "skipped", "reason": f"Unhandled source: {job.source}"}

    except Exception as e:
        logger.warning(f"Failed to trigger Bazarr rescan for job {job_id}: {e}")
        await write_job_log(
            db,
            LogLevel.WARNING,
            f"Failed to trigger Bazarr rescan: {e}",
            job_id=job_id,
        )
        return {"status": "failed", "error": str(e)}

    finally:
        await client.close()
