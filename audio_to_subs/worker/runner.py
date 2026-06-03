"""Worker job runner.

Executes claimed jobs through the pipeline with proper error handling,
progress tracking, and cost computation.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from audio_to_subs.core.cancel import Cancelled, CancelToken
from audio_to_subs.core.cost import compute_cost, extract_usage, CostBreakdown
from audio_to_subs.core.path_utils import generate_output_path
from audio_to_subs.core.pipeline import Pipeline, PipelineResult
from audio_to_subs.db.models import Job, JobStatus, JobLog, LogLevel
from audio_to_subs.queue_.claim import ClaimedJob
from audio_to_subs.queue_.events import publish_done
from audio_to_subs.worker.progress import ProgressBridge

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from redis.asyncio import Redis
    from audio_to_subs.api.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class WorkerDeps:
    """Dependencies for worker job execution.

    Attributes:
        session: Async database session
        redis: Redis async client
        settings: Application settings
        mistral_api_key: Mistral API key for transcription
    """

    session: "AsyncSession"
    redis: "Redis"
    settings: "Settings"
    mistral_api_key: str


@dataclass
class JobResult:
    """Result of a job execution."""

    status: JobStatus
    error_message: Optional[str] = None
    audio_duration_seconds: Optional[float] = None
    mistral_usage_json: Optional[str] = None
    estimated_cost_usd: Optional[float] = None


async def persist_result(
    session: "AsyncSession",
    job_id: UUID,
    result: JobResult,
) -> None:
    """Persist job result to database."""
    try:
        update_fields = {
            "status": result.status.value,
            "finished_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "error_message": result.error_message,
        }

        # Only set these if they have values
        if result.audio_duration_seconds is not None:
            update_fields["audio_duration_seconds"] = result.audio_duration_seconds
        if result.mistral_usage_json is not None:
            update_fields["mistral_usage_json"] = result.mistral_usage_json
        if result.estimated_cost_usd is not None:
            update_fields["estimated_cost_usd"] = result.estimated_cost_usd

        # Build update statement dynamically
        set_clause = ", ".join([f"{k} = :{k}" for k in update_fields.keys()])
        update_stmt = text(f"UPDATE jobs SET {set_clause} WHERE id = :job_id")

        params = {**update_fields, "job_id": str(job_id)}
        await session.execute(update_stmt, params)
        await session.commit()

    except IntegrityError:
        await session.rollback()
        logger.error(f"Integrity error persisting result for job {job_id}")
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to persist result for job {job_id}: {e}")


async def persist_log(
    session: "AsyncSession",
    job_id: UUID,
    level: LogLevel,
    message: str,
) -> None:
    """Write a log entry to the database."""
    try:
        log_entry = JobLog(
            job_id=job_id,
            ts=datetime.now(timezone.utc),
            level=level,
            message=message,
        )
        session.add(log_entry)
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to write log for job {job_id}: {e}")


async def run_job(claimed: ClaimedJob, deps: WorkerDeps) -> JobResult:
    """Execute a claimed job through the pipeline.

    This is the main entry point for job execution. It:
    1. Creates a cancellation token
    2. Sets up the progress bridge
    3. Runs the pipeline
    4. Computes cost
    5. Persists results
    6. Publishes completion events

    Args:
        claimed: The claimed job to execute
        deps: Worker dependencies (session, redis, settings, api_key)

    Returns:
        JobResult with execution outcome
    """
    job_id = claimed.id
    token = CancelToken()
    loop = asyncio.get_running_loop()

    logger.info(f"Starting job {job_id}: {claimed.media_path}")

    # Create progress bridge. The pipeline runs in a thread and calls
    # bridge.on_event synchronously; the bridge marshals DB/Redis writes back
    # onto this loop.
    bridge = ProgressBridge(
        session=deps.session,
        redis=deps.redis,
        job_id=job_id,
        token=token,
        loop=loop,
    )

    # Build output path if not provided
    output_path = claimed.output_path
    if not output_path:
        # Check if we should save subtitles alongside source files
        subtitles_same_dir = getattr(
            deps.settings, "SUBTITLES_SAME_DIRECTORY", True
        )
        # Generate output path from media path
        output_path = generate_output_path(
            claimed.media_path,
            claimed.language_code,
            claimed.output_format,
            subtitles_same_dir,
        )

    # Create pipeline
    pipeline = Pipeline(
        api_key=deps.mistral_api_key,
        structured_progress_callback=bridge.on_event,
        cancel_token=token,
        transcription_model=getattr(deps.settings, "mistral_model", "voxtral-mini-latest"),
        language=claimed.language_code,
        verbose_progress=False,  # We use structured callback
    )

    try:
        # Execute pipeline. process_video is blocking (CPU + network), so run
        # it in a thread to keep the worker's event loop free for progress
        # callbacks, Redis, and the DB.
        result: PipelineResult = await asyncio.to_thread(
            pipeline.process_video,
            claimed.media_path,
            str(output_path),
            claimed.output_format,
        )

        # Compute cost
        cost_breakdown = compute_cost(
            audio_duration_seconds=result.audio_duration_seconds,
            mistral_usage=result.mistral_usage,
            rate_usd_per_minute=getattr(
                deps.settings, "mistral_rate_usd_per_minute", 0.0
            ),
            input_token_rate_usd=getattr(
                deps.settings, "mistral_input_token_rate_usd", None
            ),
            output_token_rate_usd=getattr(
                deps.settings, "mistral_output_token_rate_usd", None
            ),
        )

        logger.info(
            f"Job {job_id} completed successfully: "
            f"duration={cost_breakdown.audio_duration_seconds}s, "
            f"cost=${cost_breakdown.estimated_cost_usd:.4f}"
        )

        # Bazarr rescan hook - notify Bazarr to rescan for new subtitles
        try:
            from audio_to_subs.db.models import JobSource

            # Check if this job came from Bazarr
            if claimed.source == JobSource.BAZARR_MOVIE:
                await _rescan_bazarr_movie(deps, claimed.source_ref, job_id)
            elif claimed.source == JobSource.BAZARR_EPISODE:
                await _rescan_bazarr_episode(deps, claimed.source_ref, job_id)
        except Exception as e:
            logger.warning(
                f"Failed to trigger Bazarr rescan for job {job_id}: {e}"
            )
            # Log but don't fail the job - this is best-effort
            await persist_log(
                deps.session,
                job_id,
                LogLevel.WARNING,
                f"Bazarr rescan failed: {str(e)}",
            )

        # Publish done event
        await publish_done(deps.redis, str(job_id), "done")

        return JobResult(
            status=JobStatus.DONE,
            audio_duration_seconds=result.audio_duration_seconds,
            mistral_usage_json=json.dumps(result.mistral_usage)
            if result.mistral_usage
            else None,
            estimated_cost_usd=cost_breakdown.estimated_cost_usd,
        )

    except Cancelled:
        logger.info(f"Job {job_id} was cancelled")

        # Publish cancelled event
        await publish_done(deps.redis, str(job_id), "cancelled")

        return JobResult(
            status=JobStatus.CANCELLED,
            error_message="Job was cancelled",
        )

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")

        # Log the error
        await persist_log(
            deps.session,
            job_id,
            LogLevel.ERROR,
            f"Job failed: {str(e)}",
        )

        # Publish failed event
        await publish_done(deps.redis, str(job_id), "failed", error=str(e))

        return JobResult(
            status=JobStatus.FAILED,
            error_message=str(e),
        )


# Helper to get path from string


async def _rescan_bazarr_movie(
    deps: WorkerDeps,
    source_ref: str | None,
    job_id: UUID,
) -> None:
    """Trigger rescan for a Bazarr movie.

    Args:
        deps: Worker dependencies
        source_ref: Radarr ID as string
        job_id: Job ID for logging
    """
    if not source_ref:
        logger.warning(f"No source_ref for Bazarr movie job {job_id}")
        return

    try:
        radarr_id = int(source_ref)
        from audio_to_subs.bazarr.client import BazarrClient

        # Get Bazarr settings from deps
        bazarr_url = getattr(deps.settings, "BAZARR_URL", None)
        bazarr_api_key = getattr(deps.settings, "BAZARR_API_KEY", None)

        if not bazarr_url or not bazarr_api_key:
            logger.info(
                f"Bazarr not configured (URL or API key missing), "
                f"skipping rescan for job {job_id}"
            )
            return

        # Create client and trigger rescan
        client = BazarrClient(
            base_url=bazarr_url,
            api_key=bazarr_api_key,
        )

        await client.rescan_movie(radarr_id)
        logger.info(f"Triggered Bazarr rescan for movie {radarr_id} (job {job_id})")

        await client.close()

    except ValueError:
        logger.warning(
            f"Invalid source_ref for Bazarr movie job {job_id}: {source_ref}"
        )
    except Exception as e:
        logger.warning(
            f"Bazarr movie rescan failed for job {job_id}: {e}"
        )
        raise


async def _rescan_bazarr_episode(
    deps: WorkerDeps,
    source_ref: str | None,
    job_id: UUID,
) -> None:
    """Trigger rescan for a Bazarr episode.

    Args:
        deps: Worker dependencies
        source_ref: Sonarr Episode ID as string
        job_id: Job ID for logging
    """
    if not source_ref:
        logger.warning(f"No source_ref for Bazarr episode job {job_id}")
        return

    try:
        sonarr_episode_id = int(source_ref)
        from audio_to_subs.bazarr.client import BazarrClient

        # Get Bazarr settings from deps
        bazarr_url = getattr(deps.settings, "BAZARR_URL", None)
        bazarr_api_key = getattr(deps.settings, "BAZARR_API_KEY", None)

        if not bazarr_url or not bazarr_api_key:
            logger.info(
                f"Bazarr not configured (URL or API key missing), "
                f"skipping rescan for job {job_id}"
            )
            return

        # Create client and trigger rescan
        client = BazarrClient(
            base_url=bazarr_url,
            api_key=bazarr_api_key,
        )

        await client.rescan_episode(sonarr_episode_id)
        logger.info(
            f"Triggered Bazarr rescan for episode {sonarr_episode_id} (job {job_id})"
        )

        await client.close()

    except ValueError:
        logger.warning(
            f"Invalid source_ref for Bazarr episode job {job_id}: {source_ref}"
        )
    except Exception as e:
        logger.warning(
            f"Bazarr episode rescan failed for job {job_id}: {e}"
        )
        raise
