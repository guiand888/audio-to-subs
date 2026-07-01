"""Bazarr poller for caching wanted items.

Periodically polls Bazarr API for wanted subtitles and updates the local cache.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update, delete, func, or_
from sqlalchemy.orm import Mapped

from audio_to_subs.bazarr.client import BazarrClient
from audio_to_subs.bazarr.pathmap import PathMap
from audio_to_subs.bazarr.schemas import BazarrEpisode, BazarrMovie
from audio_to_subs.db.models import BazarrCache

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


class PollerState:
    """State for the Bazarr poller."""

    def __init__(self) -> None:
        self.shutdown = asyncio.Event()
        self.poll_task: asyncio.Task | None = None


async def get_bazarr_client(
    bazarr_url: str | None,
    bazarr_api_key: str | None,
) -> BazarrClient | None:
    """Get Bazarr client if configured.

    Args:
        bazarr_url: Bazarr API URL from settings
        bazarr_api_key: Bazarr API key from settings

    Returns:
        Configured BazarrClient or None if not configured
    """
    if not bazarr_url or not bazarr_api_key:
        logger.debug("Bazarr not configured (missing URL or API key)")
        return None

    return BazarrClient(
        base_url=bazarr_url,
        api_key=bazarr_api_key,
    )


async def get_path_map(
    db: "AsyncSession",
) -> PathMap:
    """Get PathMap from settings.

    Args:
        db: Async database session

    Returns:
        PathMap configured from settings or empty PathMap
    """
    # Import here to avoid circular imports
    from audio_to_subs.db.models import Setting

    try:
        result = await db.execute(
            select(Setting.value_json).where(Setting.key == "path_mappings")
        )
        # scalar_one_or_none() returns the raw value_json string, not a Setting.
        value_json = result.scalar_one_or_none()
        if value_json:
            import json

            path_mappings = json.loads(value_json)
            return PathMap.from_settings(path_mappings)
    except Exception as e:
        logger.warning("Failed to load path_mappings from settings: %s", e)

    return PathMap()


async def get_settings_value(
    db: "AsyncSession",
    key: str,
    default: Any = None,
) -> Any:
    """Get a setting value from the database.

    Args:
        db: Async database session
        key: Setting key
        default: Default value if not found

    Returns:
        Setting value or default
    """
    from audio_to_subs.db.models import Setting

    try:
        result = await db.execute(
            select(Setting.value_json).where(Setting.key == key)
        )
        # scalar_one_or_none() returns the raw value_json string, not a Setting.
        value_json = result.scalar_one_or_none()
        if value_json:
            import json

            return json.loads(value_json)
    except Exception as e:
        logger.warning("Failed to load setting %s: %s", key, e)

    return default


async def get_track_no_subs(db: "AsyncSession") -> bool:
    """Check if bazarr_track_no_subs is enabled."""
    return await get_settings_value(db, "bazarr_track_no_subs", False)


async def poll_once(
    db: "AsyncSession",
    client: BazarrClient,
    path_map: PathMap,
) -> int:
    """Perform a single poll of Bazarr wanted items.

    Fetches wanted movies and episodes from Bazarr, translates paths,
    and updates the bazarr_cache table.

    Args:
        db: Async database session
        client: BazarrClient instance
        path_map: PathMap for path translation

    Returns:
        Number of items processed
    """
    from sqlalchemy import insert

    started_at = datetime.now(timezone.utc)
    logger.info("Starting Bazarr poll at %s", started_at.isoformat())

    total_processed = 0

    try:
        # Check if we should track items with no subs at all
        track_no_subs = await get_track_no_subs(db)

        # Process wanted movies
        movies_page = await client.list_wanted_movies(length=200)
        for movie in movies_page.data:
            await _process_movie(db, movie, path_map, started_at)
            total_processed += 1

        # Process wanted episodes
        episodes_page = await client.list_wanted_episodes(length=200)
        for episode in episodes_page.data:
            await _process_episode(db, episode, path_map, started_at)
            total_processed += 1

        # If tracking no-subs items, also check all items
        if track_no_subs:
            await _poll_all_movies(db, client, path_map, started_at)
            await _poll_all_episodes(db, client, path_map, started_at)

        # Delete stale items (no longer wanted)
        deleted_count = await _delete_stale(db, started_at)
        if deleted_count > 0:
            logger.info("Deleted %d stale items from cache", deleted_count)

        logger.info(
            "Bazarr poll complete: processed %d items, deleted %d stale",
            total_processed,
            deleted_count,
        )

    except Exception as e:
        logger.error("Error during Bazarr poll: %s", e, exc_info=True)
        raise

    return total_processed


async def _process_movie(
    db: "AsyncSession",
    wanted_movie: Any,
    path_map: PathMap,
    started_at: datetime,
) -> None:
    """Process a single wanted movie.

    Args:
        db: Async database session
        wanted_movie: WantedMovie from Bazarr API
        path_map: PathMap for path translation
        started_at: Poll start time
    """
    # Translate sceneName to media_path if available
    media_path = wanted_movie.sceneName or ""
    if media_path:
        media_path = path_map.translate(media_path)

    # Check if this movie has any subtitles at all
    has_any_subs = len(wanted_movie.missing_subtitles or []) > 0

    cache_id = BazarrCache.make_id("movie", wanted_movie.radarrId)

    # Use merge (upsert) - SQLite doesn't support ON CONFLICT directly in SQLAlchemy 2.x
    # We'll do a select-then-update/insert pattern
    result = await db.execute(
        select(BazarrCache).where(BazarrCache.id == cache_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing record
        existing.title = wanted_movie.title
        existing.media_path = media_path
        existing.has_any_subs = has_any_subs
        existing.missing_subtitles = [
            {
                "name": lang.name,
                "code2": lang.code2,
                "code3": lang.code3,
                "forced": lang.forced,
                "hi": lang.hi,
            }
            for lang in (wanted_movie.missing_subtitles or [])
        ]
        existing.last_polled = started_at
    else:
        # Insert new record
        cache_entry = BazarrCache(
            id=cache_id,
            kind="movie",
            ext_id=wanted_movie.radarrId,
            title=wanted_movie.title,
            media_path=media_path,
            has_any_subs=has_any_subs,
            missing_subtitles=[
                {
                    "name": lang.name,
                    "code2": lang.code2,
                    "code3": lang.code3,
                    "forced": lang.forced,
                    "hi": lang.hi,
                }
                for lang in (wanted_movie.missing_subtitles or [])
            ],
            last_polled=started_at,
            active_job_id=None,
        )
        db.add(cache_entry)

    await db.commit()


async def _process_episode(
    db: "AsyncSession",
    wanted_episode: Any,
    path_map: PathMap,
    started_at: datetime,
) -> None:
    """Process a single wanted episode.

    Args:
        db: Async database session
        wanted_episode: WantedEpisode from Bazarr API
        path_map: PathMap for path translation
        started_at: Poll start time
    """
    # Translate sceneName to media_path if available
    media_path = wanted_episode.sceneName or ""
    if media_path:
        media_path = path_map.translate(media_path)

    # Check if this episode has any subtitles at all
    has_any_subs = len(wanted_episode.missing_subtitles or []) > 0

    cache_id = BazarrCache.make_id("episode", wanted_episode.sonarrEpisodeId)

    # Upsert logic
    result = await db.execute(
        select(BazarrCache).where(BazarrCache.id == cache_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing record
        existing.title = f"{wanted_episode.seriesTitle} - {wanted_episode.episodeTitle}"
        existing.media_path = media_path
        existing.has_any_subs = has_any_subs
        existing.missing_subtitles = [
            {
                "name": lang.name,
                "code2": lang.code2,
                "code3": lang.code3,
                "forced": lang.forced,
                "hi": lang.hi,
            }
            for lang in (wanted_episode.missing_subtitles or [])
        ]
        existing.last_polled = started_at
    else:
        # Insert new record
        cache_entry = BazarrCache(
            id=cache_id,
            kind="episode",
            ext_id=wanted_episode.sonarrEpisodeId,
            title=f"{wanted_episode.seriesTitle} - {wanted_episode.episodeTitle}",
            media_path=media_path,
            has_any_subs=has_any_subs,
            missing_subtitles=[
                {
                    "name": lang.name,
                    "code2": lang.code2,
                    "code3": lang.code3,
                    "forced": lang.forced,
                    "hi": lang.hi,
                }
                for lang in (wanted_episode.missing_subtitles or [])
            ],
            last_polled=started_at,
            active_job_id=None,
        )
        db.add(cache_entry)

    await db.commit()


async def _poll_all_movies(
    db: "AsyncSession",
    client: BazarrClient,
    path_map: PathMap,
    started_at: datetime,
) -> None:
    """Poll all movies and add those with no subtitles to cache.

    This is expensive and opt-in via bazarr_track_no_subs setting.

    Args:
        db: Async database session
        client: BazarrClient instance
        path_map: PathMap for path translation
        started_at: Poll start time
    """
    try:
        movies_page = await client.list_all_movies(length=200)
        for movie in movies_page.data:
            # Check if movie has no subtitles at all
            if not movie.subtitles:
                media_path = movie.sceneName or ""
                if media_path:
                    media_path = path_map.translate(media_path)

                cache_id = BazarrCache.make_id("movie", movie.radarrId)

                # Upsert - only if not already in cache from wanted list
                result = await db.execute(
                    select(BazarrCache).where(BazarrCache.id == cache_id)
                )
                existing = result.scalar_one_or_none()

                if not existing:
                    cache_entry = BazarrCache(
                        id=cache_id,
                        kind="movie",
                        ext_id=movie.radarrId,
                        title=movie.title,
                        media_path=media_path,
                        has_any_subs=False,
                        missing_subtitles=[],  # Empty because we don't know what's missing
                        last_polled=started_at,
                        active_job_id=None,
                    )
                    db.add(cache_entry)

        await db.commit()
    except Exception as e:
        logger.warning("Failed to poll all movies: %s", e)


async def _poll_all_episodes(
    db: "AsyncSession",
    client: BazarrClient,
    path_map: PathMap,
    started_at: datetime,
) -> None:
    """Poll all episodes and add those with no subtitles to cache.

    This is expensive and opt-in via bazarr_track_no_subs setting.

    Args:
        db: Async database session
        client: BazarrClient instance
        path_map: PathMap for path translation
        started_at: Poll start time
    """
    # This would need to iterate through all series first
    # For now, skip this as it's very expensive
    # Can be implemented if needed by fetching all series, then all episodes per series
    logger.debug("Skipping all episodes poll - not yet implemented")


async def _delete_stale(
    db: "AsyncSession",
    started_at: datetime,
) -> int:
    """Delete items that are no longer wanted.

    Removes items from cache where last_polled < started_at
    (meaning they were not seen in the current poll cycle).

    Args:
        db: Async database session
        started_at: Poll start time

    Returns:
        Number of deleted items
    """
    result = await db.execute(
        delete(BazarrCache).where(BazarrCache.last_polled < started_at)
    )
    await db.commit()
    return result.rowcount


async def _get_poll_interval(db: "AsyncSession") -> int:
    """Get poll interval from settings.

    Args:
        db: Async database session

    Returns:
        Poll interval in seconds (default: 3600)
    """
    return await get_settings_value(db, "bazarr_poll_interval", 3600)


async def run_bazarr_poller(app: "FastAPI") -> None:
    """Run the Bazarr poller as an asyncio task.

    This is designed to be started in the FastAPI lifespan.
    Respects the app's shutdown signal.

    Args:
        app: FastAPI application instance
    """
    from audio_to_subs.api.settings import get_settings

    settings = get_settings()

    # Get DB session factory
    from audio_to_subs.db.session import get_async_session

    interval = 3600  # fallback if the session fails before _get_poll_interval runs

    while not app.state.shutdown.is_set():
        try:
            async with get_async_session(settings.DATABASE_URL) as db:
                interval = await _get_poll_interval(db)

                client = await get_bazarr_client(
                    settings.BAZARR_URL,
                    settings.BAZARR_API_KEY,
                )

                if client is None:
                    logger.debug(
                        "Bazarr not configured, skipping poll (waiting %d seconds)",
                        interval,
                    )
                else:
                    path_map = await get_path_map(db)
                    try:
                        await poll_once(db, client, path_map)
                    except Exception as e:
                        logger.warning("Bazarr poll failed: %s", e)
                    finally:
                        await client.close()

        except Exception as e:
            logger.error("Bazarr poller error: %s", e, exc_info=True)

        # Session is closed before this sleep — no write lock held during wait.
        try:
            await asyncio.wait_for(
                app.state.shutdown.wait(),
                timeout=interval,
            )
        except asyncio.TimeoutError:
            pass  # interval elapsed → next poll
        except asyncio.CancelledError:
            break


async def start_poller(app: "FastAPI") -> None:
    """Start the Bazarr poller task in the FastAPI app state.

    Args:
        app: FastAPI application instance
    """
    if not hasattr(app.state, "poller_task"):
        app.state.poller_task = None

    if app.state.poller_task is None or app.state.poller_task.done():
        app.state.poller_task = asyncio.create_task(run_bazarr_poller(app))
        logger.info("Bazarr poller task started")


async def stop_poller(app: "FastAPI") -> None:
    """Stop the Bazarr poller task.

    Args:
        app: FastAPI application instance
    """
    if hasattr(app.state, "poller_task") and app.state.poller_task:
        app.state.poller_task.cancel()
        try:
            await app.state.poller_task
        except asyncio.CancelledError:
            logger.info("Bazarr poller task cancelled")
        app.state.poller_task = None
