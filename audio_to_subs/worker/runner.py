"""Worker job runner.

Executes claimed jobs through the pipeline with proper error handling,
progress tracking, and cost computation.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, Optional, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from audio_to_subs.core.cancel import Cancelled, CancelToken
from audio_to_subs.core.cost import compute_cost
from audio_to_subs.core.models import (
    DEFAULT_MAX_AUDIO_LENGTH,
    MODEL_SPECS,
)
from audio_to_subs.core.path_utils import generate_output_path
from audio_to_subs.core.pipeline import Pipeline, PipelineResult
from audio_to_subs.db.models import Job, JobLog, JobStatus, LogLevel, Setting
from audio_to_subs.queue_.claim import ClaimedJob
from audio_to_subs.queue_.events import publish_done
from audio_to_subs.worker.progress import ProgressBridge

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

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
        database_url: Database connection URL for creating per-write sessions
    """

    session: "AsyncSession"
    redis: "Redis"
    settings: "Settings"
    mistral_api_key: str
    database_url: str


@dataclass
class JobResult:
    """Result of a job execution."""

    status: JobStatus
    error_message: Optional[str] = None
    audio_duration_seconds: Optional[float] = None
    mistral_usage_json: Optional[str] = None
    estimated_cost_usd: Optional[float] = None
    detected_language: Optional[str] = None
    language_mode: Optional[str] = None


async def persist_result(
    session: "AsyncSession",
    job_id: str,
    result: JobResult,
) -> None:
    """Persist job result to database."""
    try:
        job = await session.get(Job, job_id)
        if job:
            job.status = result.status
            job.finished_at = datetime.now(timezone.utc)
            job.updated_at = datetime.now(timezone.utc)
            job.error_message = result.error_message

            if result.audio_duration_seconds is not None:
                job.audio_duration_seconds = result.audio_duration_seconds
            if result.mistral_usage_json is not None:
                job.mistral_usage_json = result.mistral_usage_json
            if result.estimated_cost_usd is not None:
                job.estimated_cost_usd = result.estimated_cost_usd
            if result.detected_language is not None:
                job.mistral_detected_language = result.detected_language
            if result.language_mode == "auto":
                resolved = result.detected_language or "und"
                job.language_code = resolved
                job.needs_language_review = result.detected_language is None

            await session.commit()
        else:
            logger.error(f"Job {job_id} not found for result persistence")

    except IntegrityError:
        await session.rollback()
        logger.error(f"Integrity error persisting result for job {job_id}")
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to persist result for job {job_id}: {e}")


async def persist_log(
    session: "AsyncSession",
    job_id: str,
    level: LogLevel,
    message: str,
) -> None:
    """Write a log entry to the database."""
    try:
        log_entry = JobLog(
            job_id=str(job_id),
            ts=datetime.now(timezone.utc),
            level=level,
            message=message,
        )
        session.add(log_entry)
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to write log for job {job_id}: {e}")


async def _get_db_settings(session: "AsyncSession") -> dict[str, Any]:
    """Fetch current settings from the database.

    Returns a dict with settings that override environment defaults.
    Worker must read from DB (not environment) so that UI-changed settings
    affect active jobs.
    """
    settings_dict = {}
    try:
        result = await session.execute(select(Setting))
        for setting in result.scalars().all():
            if setting.key in (
                "SUBTITLES_SAME_DIRECTORY",
                "mistral_model",
                "mistral_rate_usd_per_minute",
                "mistral_input_token_rate_usd",
                "mistral_output_token_rate_usd",
                "max_audio_length",
            ):
                # Parse JSON if needed
                value = setting.value_json or setting.value
                if setting.value_json:
                    try:
                        import json

                        value = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        value = setting.value
                settings_dict[setting.key] = value
    except Exception as e:
        logger.warning(f"Failed to fetch settings from DB: {e}")
    return settings_dict


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
    # onto this loop using per-write sessions to avoid concurrent access issues.
    bridge = ProgressBridge(
        database_url=deps.database_url,
        redis=deps.redis,
        job_id=job_id,
        token=token,
        loop=loop,
    )

    # Fetch settings from DB (worker must use DB settings, not cached env settings,
    # so that UI-changed settings affect running jobs)
    db_settings = await _get_db_settings(deps.session)

    # Use DB settings with env defaults as fallback
    subtitles_same_dir = db_settings.get(
        "SUBTITLES_SAME_DIRECTORY",
        getattr(deps.settings, "SUBTITLES_SAME_DIRECTORY", True),
    )
    mistral_model = db_settings.get(
        "mistral_model", getattr(deps.settings, "mistral_model", "voxtral-mini-2602")
    )
    mistral_rate = db_settings.get(
        "mistral_rate_usd_per_minute",
        getattr(deps.settings, "mistral_rate_usd_per_minute", 0.0),
    )
    input_token_rate = db_settings.get(
        "mistral_input_token_rate_usd",
        getattr(deps.settings, "mistral_input_token_rate_usd", None),
    )
    output_token_rate = db_settings.get(
        "mistral_output_token_rate_usd",
        getattr(deps.settings, "mistral_output_token_rate_usd", None),
    )
    max_audio_length_setting = db_settings.get(
        "max_audio_length",
        getattr(deps.settings, "max_audio_length", DEFAULT_MAX_AUDIO_LENGTH),
    )

    # Compute effective max_audio_length: min(setting, model preset cap)
    model_cap = MODEL_SPECS.get(mistral_model, {}).get(
        "max_audio_length", DEFAULT_MAX_AUDIO_LENGTH
    )
    effective_max_audio_length = min(int(max_audio_length_setting), int(model_cap))

    # Build output path if not provided
    output_path = claimed.output_path
    if not output_path:
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
        transcription_model=mistral_model,
        language=claimed.language_code,
        verbose_progress=False,  # We use structured callback
        max_audio_length=effective_max_audio_length,
        # ClaimedJob.language_mode is a raw DB column typed as str, but the
        # API layer (JobCreateRequest.language_mode: Literal) guarantees it's
        # always one of these two values.
        language_mode=cast(Literal["auto", "explicit"], claimed.language_mode),
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

        # Compute cost using DB settings
        cost_breakdown = compute_cost(
            audio_duration_seconds=result.audio_duration_seconds,
            mistral_usage=result.mistral_usage,
            rate_usd_per_minute=mistral_rate,
            input_token_rate_usd=input_token_rate,
            output_token_rate_usd=output_token_rate,
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
            logger.warning(f"Failed to trigger Bazarr rescan for job {job_id}: {e}")
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
            mistral_usage_json=(
                json.dumps(result.mistral_usage) if result.mistral_usage else None
            ),
            estimated_cost_usd=cost_breakdown.estimated_cost_usd,
            detected_language=result.detected_language,
            language_mode=claimed.language_mode,
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
    job_id: str,
) -> None:
    """Trigger rescan for a Bazarr movie.

    Uses database settings first, falling back to environment variables.

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
        from audio_to_subs.bazarr.poller import get_bazarr_client_with_settings

        # Get Bazarr client using database settings first, then environment fallback
        client, bazarr_url, bazarr_api_key, bazarr_timeout = (
            await get_bazarr_client_with_settings(deps.session, deps.settings)
        )

        if client is None:
            logger.info(
                f"Bazarr not configured (URL or API key missing), "
                f"skipping rescan for job {job_id}"
            )
            return

        try:
            # Trigger rescan
            await client.rescan_movie(radarr_id)
            logger.info(f"Triggered Bazarr rescan for movie {radarr_id} (job {job_id})")
        finally:
            await client.close()

    except ValueError:
        logger.warning(
            f"Invalid source_ref for Bazarr movie job {job_id}: {source_ref}"
        )
    except Exception as e:
        logger.warning(f"Bazarr movie rescan failed for job {job_id}: {e}")
        raise


async def _rescan_bazarr_episode(
    deps: WorkerDeps,
    source_ref: str | None,
    job_id: str,
) -> None:
    """Trigger rescan for a Bazarr episode.

    Uses database settings first, falling back to environment variables.

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
        from audio_to_subs.bazarr.poller import get_bazarr_client_with_settings

        # Get Bazarr client using database settings first, then environment fallback
        client, bazarr_url, bazarr_api_key, bazarr_timeout = (
            await get_bazarr_client_with_settings(deps.session, deps.settings)
        )

        if client is None:
            logger.info(
                f"Bazarr not configured (URL or API key missing), "
                f"skipping rescan for job {job_id}"
            )
            return

        try:
            # Fetch episode to get series_id (Bazarr doesn't support per-episode rescan)
            try:
                episode = await client.get_episode(sonarr_episode_id)
            except Exception as e:
                logger.warning(
                    f"Failed to fetch series_id for episode {sonarr_episode_id}: {e}"
                )
                return

            if episode is None:
                logger.warning(
                    f"Episode {sonarr_episode_id} not found in Bazarr. "
                    f"Job {job_id}: skipping rescan."
                )
                return

            series_id = episode.sonarrSeriesId

            # Trigger rescan with series_id
            await client.rescan_episode(sonarr_episode_id, series_id=series_id)
            logger.info(
                f"Triggered Bazarr rescan for series {series_id} "
                f"(containing episode {sonarr_episode_id}, job {job_id})"
            )
        finally:
            await client.close()

    except ValueError:
        logger.warning(
            f"Invalid source_ref for Bazarr episode job {job_id}: {source_ref}"
        )
    except Exception as e:
        logger.warning(f"Bazarr episode rescan failed for job {job_id}: {e}")
        raise
