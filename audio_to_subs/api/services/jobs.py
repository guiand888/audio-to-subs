"""Job service layer for job creation and management."""

import json
import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select

from audio_to_subs.bazarr.pathmap import PathMap
from audio_to_subs.core.path_utils import generate_output_path, validate_media_path
from audio_to_subs.db.job_logs import write_job_log
from audio_to_subs.db.models import (
    BazarrCache,
    Job,
    JobSource,
    JobStatus,
    LogLevel,
    OutputFormat,
    Setting,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from audio_to_subs.api.settings import Settings

logger = logging.getLogger(__name__)


async def get_path_map(db: "AsyncSession") -> PathMap:
    """Get PathMap from database settings.

    Args:
        db: Async database session

    Returns:
        PathMap configured from database
    """
    return await PathMap.load_from_db(db)


async def resolve_bazarr_source(
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


async def get_default_language_code(db: "AsyncSession") -> str | None:
    """Get default language code from settings.

    Args:
        db: Database session

    Returns:
        Default language code or None
    """

    try:
        result = await db.execute(
            select(Setting.value_json).where(Setting.key == "default_language")
        )
        value_json = result.scalar_one_or_none()
        if value_json:
            return str(json.loads(value_json))
    except Exception:
        pass

    return None


async def get_default_output_format(db: "AsyncSession") -> OutputFormat | None:
    """Get default output format from settings.

    Args:
        db: Database session

    Returns:
        Default output format or None
    """

    try:
        result = await db.execute(
            select(Setting.value_json).where(Setting.key == "default_output_format")
        )
        value_json = result.scalar_one_or_none()
        if value_json:
            default_format = json.loads(value_json)
            if default_format and default_format != "srt":
                try:
                    return OutputFormat(default_format)
                except ValueError:
                    pass  # Invalid format, keep default
    except Exception:
        pass

    return None


async def _apply_language_and_format_defaults(
    db: "AsyncSession",
    language_code: str | None,
    output_format: OutputFormat,
    language_mode: str,
) -> tuple[str | None, OutputFormat]:
    """Resolve the final language code and output format from settings defaults.

    Auto mode must never pick up the default-language setting - the real
    language isn't known until the worker finishes transcribing.
    """
    final_language_code = language_code
    if final_language_code is None and language_mode != "auto":
        final_language_code = await get_default_language_code(db)

    final_output_format = output_format
    if final_output_format == OutputFormat.SRT:
        default_format = await get_default_output_format(db)
        if default_format:
            final_output_format = default_format

    return final_language_code, final_output_format


async def create_job_service(
    db: "AsyncSession",
    settings: "Settings",
    source: JobSource,
    source_ref: str | None,
    media_path: str | None,
    output_path: str | None,
    language_code: str | None,
    output_format: OutputFormat,
    priority: int,
    language_mode: str = "explicit",
) -> Job:
    """Create a new transcription job.

    Creates a job in 'queued' state. The caller is responsible for publishing
    the job notification to Redis.

    Args:
        db: Async database session
        settings: Settings object
        source: Job source
        source_ref: Reference to external source (e.g., Bazarr ID)
        media_path: Path to the media file to process
        output_path: Path where output subtitles should be written
        language_code: Language code for transcription
        output_format: Output subtitle format
        priority: Job priority
        language_mode: "auto" or "explicit". When "auto", language_code is
            ignored (forced to None) - the real language isn't known until
            the worker finishes transcribing, and auto mode must never pick
            up the default-language setting.

    Returns:
        Created Job object

    Raises:
        HTTPException: If validation fails or source resolution fails
    """
    if language_mode == "auto":
        language_code = None

    # Get path map for path translation
    path_map = await get_path_map(db)

    # Resolve media_path based on source
    try:
        resolved_media_path, resolved_source_ref = await resolve_bazarr_source(
            db,
            source,
            source_ref,
            media_path,
            path_map,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to resolve Bazarr source: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to resolve source. Please check your source configuration.",
        ) from e

    # An empty media_path can't be transcribed. For bazarr sources this
    # happens when the item is cached without a usable file path (e.g.
    # Bazarr's wanted endpoint reports no sceneName and the full-detail
    # path is also missing). Surface a clear, actionable error rather than
    # the generic root-directory validation message below.
    if not resolved_media_path or not resolved_media_path.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No media file path is available for this item from Bazarr. "
                "Refresh the wanted list and try again; if the path is still "
                "missing, the media file may not exist on disk."
            ),
        )

    # Validate media_path against configured root paths (validate_media_path
    # also rejects path traversal, control characters, and relative paths).
    movies_root = getattr(settings, "MOVIES_ROOT_PATH", None)
    tv_root = getattr(settings, "TV_ROOT_PATH", None)

    is_valid, error_msg = validate_media_path(resolved_media_path, movies_root, tv_root)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid media path: {error_msg}",
        )

    # Apply defaults from settings if not provided.
    final_language_code, final_output_format = (
        await _apply_language_and_format_defaults(
            db, language_code, output_format, language_mode
        )
    )

    # Auto-generate output_path if not provided and subtitles_same_directory is
    # enabled. Uses final_language_code (post-defaulting), not the raw
    # parameter, so a job relying on the default-language setting gets a path
    # with the right language suffix instead of none.
    subtitles_same_dir = getattr(settings, "SUBTITLES_SAME_DIRECTORY", True)
    final_output_path = output_path
    if not final_output_path and subtitles_same_dir:
        final_output_path = generate_output_path(
            resolved_media_path,
            final_language_code,
            final_output_format.value,
            subtitles_same_dir,
        )
    elif final_output_path:
        # Validate provided output_path is within safe directory
        is_valid, error_msg = validate_media_path(
            final_output_path, movies_root, tv_root
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid output path: {error_msg}",
            )

    # Create job
    job = Job(
        id=str(uuid4()),
        status=JobStatus.QUEUED,
        source=source,
        source_ref=resolved_source_ref or source_ref,
        media_path=resolved_media_path,
        output_path=final_output_path,
        language_code=final_language_code,
        language_mode=language_mode,
        output_format=final_output_format,
        priority=priority,
        progress_percent=0,
        progress_message="Job created, waiting for worker",
        cancel_requested=False,
    )

    db.add(job)
    await db.commit()
    await db.refresh(job)

    await write_job_log(
        db,
        LogLevel.INFO,
        f"Job created: source={source.value}, media_path={resolved_media_path}",
        job_id=job.id,
    )

    return job
