"""Bazarr poller for caching wanted items.

Periodically polls Bazarr API for wanted subtitles and updates the local cache.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, or_, select

from audio_to_subs.bazarr.client import BazarrClient
from audio_to_subs.bazarr.pathmap import PathMap
from audio_to_subs.db.models import BazarrCache

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from audio_to_subs.api.settings import Settings
    from audio_to_subs.bazarr.schemas import Episode, Movie

logger = logging.getLogger(__name__)


class PollerState:
    """State for the Bazarr poller."""

    def __init__(self) -> None:
        self.shutdown = asyncio.Event()
        self.poll_task: asyncio.Task | None = None


async def get_bazarr_client(
    bazarr_url: str | None = None,
    bazarr_api_key: str | None = None,
    bazarr_timeout: float = 30.0,
) -> BazarrClient | None:
    """Get Bazarr client if configured.

    Args:
        bazarr_url: Bazarr API URL from settings
        bazarr_api_key: Bazarr API key from settings
        bazarr_timeout: Bazarr API timeout in seconds

    Returns:
        Configured BazarrClient or None if not configured
    """
    if not bazarr_url or not bazarr_api_key:
        logger.debug("Bazarr not configured (missing URL or API key)")
        return None

    return BazarrClient(
        base_url=bazarr_url,
        api_key=bazarr_api_key,
        timeout=bazarr_timeout,
    )


async def get_bazarr_client_with_settings(
    db: "AsyncSession",
    env_settings: "Settings | None" = None,
) -> tuple[BazarrClient | None, str | None, str | None, float]:
    """Get Bazarr client with settings from database first, then environment fallback.

    This function prioritizes database settings over environment variables. A
    missing DB row or a DB value of None (including the row seeded by
    `_seed_default_settings`, before a user has ever configured Bazarr) falls
    back to the environment; an explicit empty string in the DB is treated as
    the user deliberately disabling Bazarr and is not overridden.

    Args:
        db: Async database session
        env_settings: Optional environment settings (for testing)

    Returns:
        Tuple of (BazarrClient or None, bazarr_url, bazarr_api_key, bazarr_timeout)
        Returns None for client if not configured
    """
    import json

    from audio_to_subs.db.models import Setting

    keys = ("bazarr_url", "bazarr_api_key", "bazarr_timeout")
    db_values: dict[str, Any] = {}
    try:
        result = await db.execute(
            select(Setting.key, Setting.value_json).where(Setting.key.in_(keys))
        )
        for key, value_json in result.all():
            if value_json:
                db_values[key] = json.loads(value_json)
    except Exception as e:
        logger.warning("Failed to load Bazarr settings: %s", e)

    bazarr_url = db_values.get("bazarr_url")
    bazarr_api_key = db_values.get("bazarr_api_key")
    bazarr_timeout = db_values.get("bazarr_timeout")

    # Fall back to environment settings if database settings are not set
    if env_settings is None:
        from audio_to_subs.api.settings import get_settings

        env_settings = get_settings()

    # A DB value of None (row absent, or seeded default) falls back to env.
    # An explicit "" is a deliberate "disable Bazarr" signal and is kept as-is.
    if bazarr_url is None:
        bazarr_url = env_settings.BAZARR_URL
    if bazarr_api_key is None:
        # Use the property which handles file-based loading from BAZARR_API_KEY_FILE
        bazarr_api_key = env_settings.bazarr_api_key
    if bazarr_timeout is None:
        bazarr_timeout = env_settings.BAZARR_TIMEOUT

    client = await get_bazarr_client(bazarr_url, bazarr_api_key, bazarr_timeout)
    return client, bazarr_url, bazarr_api_key, bazarr_timeout


async def get_path_map(
    db: "AsyncSession",
) -> PathMap:
    """Get PathMap from settings.

    Args:
        db: Async database session

    Returns:
        PathMap configured from settings or empty PathMap
    """
    return await PathMap.load_from_db(db)


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
        result = await db.execute(select(Setting.value_json).where(Setting.key == key))
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
    """Perform a single scheduled poll of all Bazarr wanted items.

    Fetches wanted movies and episodes from Bazarr, translates paths,
    and updates the bazarr_cache table.

    Args:
        db: Async database session
        client: BazarrClient instance
        path_map: PathMap for path translation

    Returns:
        Number of items processed
    """
    movies_processed, episodes_processed = await poll_bazarr_manually(
        db, client, path_map, "all"
    )
    return movies_processed + episodes_processed


async def poll_bazarr_manually(
    db: "AsyncSession",
    client: BazarrClient,
    path_map: PathMap,
    item_type: str | None = None,
) -> tuple[int, int]:
    """Perform a poll of Bazarr items with optional type filtering.

    Used both for the scheduled background poll (via poll_once, item_type="all")
    and for on-demand manual refreshes triggered from the API. Respects the
    bazarr_track_no_subs setting and returns separate counts for movies and
    episodes processed.

    Runs strictly sequentially: `db` is a single SQLAlchemy AsyncSession, which
    does not support concurrent use from multiple coroutines (interleaved
    `execute()`/`commit()` calls raise `IllegalStateChangeError`), so movies and
    episodes cannot be processed via asyncio.gather() against the same session.

    Args:
        db: Async database session
        client: BazarrClient instance
        path_map: PathMap for path translation
        item_type: Optional filter - one of "all", "movie", "episode".
            If None or "all", polls both movies and episodes.
            If "movie", polls only movies.
            If "episode", polls only episodes.

    Returns:
        Tuple of (movies_processed, episodes_processed) counts
    """
    started_at = datetime.now(timezone.utc)
    logger.info(
        "Starting Bazarr poll at %s (item_type=%s)", started_at.isoformat(), item_type
    )

    movies_processed = 0
    episodes_processed = 0

    try:
        # Check if we should track items with no subs at all
        track_no_subs = await get_track_no_subs(db)

        # Determine which types to poll
        poll_movies = item_type is None or item_type == "all" or item_type == "movie"
        poll_episodes = (
            item_type is None or item_type == "all" or item_type == "episode"
        )

        # Process wanted movies
        if poll_movies:
            movies_page = await client.list_wanted_movies(length=200)
            movie_details = await _fetch_movie_details(
                client, [m.radarrId for m in movies_page.data]
            )
            for movie in movies_page.data:
                movie_detail = movie_details.get(movie.radarrId)
                await _process_movie(
                    db,
                    movie,
                    path_map,
                    started_at,
                    movie_detail.audio_language if movie_detail else None,
                    movie_detail.path if movie_detail else None,
                )
                movies_processed += 1

        # Process wanted episodes
        if poll_episodes:
            episodes_page = await client.list_wanted_episodes(length=200)
            episode_details = await _fetch_episode_details(
                client, {e.sonarrSeriesId for e in episodes_page.data}
            )
            for episode in episodes_page.data:
                episode_detail = episode_details.get(episode.sonarrEpisodeId)
                await _process_episode(
                    db,
                    episode,
                    path_map,
                    started_at,
                    episode_detail.audio_language if episode_detail else None,
                    episode_detail.path if episode_detail else None,
                )
                episodes_processed += 1

        # If tracking no-subs items, also check all items
        if track_no_subs:
            if poll_movies:
                await _poll_all_movies(db, client, path_map, started_at)
            if poll_episodes:
                await _poll_all_episodes(db, client, path_map, started_at)

        # Delete stale items (no longer wanted) - only for types that were polled
        deleted_count = await _delete_stale(db, started_at, poll_movies, poll_episodes)
        if deleted_count > 0:
            logger.info("Deleted %d stale items from cache", deleted_count)

        logger.info(
            "Bazarr poll complete: processed %d movies, %d episodes, deleted %d stale",
            movies_processed,
            episodes_processed,
            deleted_count,
        )

    except Exception as e:
        logger.error("Error during Bazarr poll: %s", e, exc_info=True)
        raise

    return movies_processed, episodes_processed


async def _fetch_movie_details(
    client: BazarrClient, radarr_ids: list[int]
) -> dict[int, "Movie"]:
    """Batch-fetch full movie details (audio_language + path) by Radarr ID.

    Bazarr's wanted-movies endpoint carries neither audio_language nor a
    usable file path (sceneName is null there), so both must be joined in
    from the full-detail endpoint. One HTTP call per poll cycle for exactly
    the movies being processed, not one per item.

    Args:
        client: BazarrClient instance
        radarr_ids: Radarr IDs to look up

    Returns:
        Dict mapping radarrId to its full Movie (missing entries mean
        Bazarr couldn't report details for that movie)
    """
    if not radarr_ids:
        return {}
    try:
        full_movies = await client.list_all_movies(radarrid=radarr_ids)
        return {m.radarrId: m for m in full_movies.data}
    except Exception as e:
        logger.warning("Failed to fetch movie details: %s", e)
        return {}


async def _fetch_episode_details(
    client: BazarrClient, series_ids: set[int]
) -> dict[int, "Episode"]:
    """Batch-fetch full episode details (audio_language + path), by series.

    Bazarr's wanted-episodes endpoint carries neither audio_language nor a
    usable file path (sceneName is null there), and its episodes endpoint
    only accepts a single series ID (not a list), so this batches by unique
    series rather than per-episode - bounded by "distinct series with wanted
    episodes this poll", not one call per episode.

    Args:
        client: BazarrClient instance
        series_ids: Unique Sonarr series IDs to look up

    Returns:
        Dict mapping sonarrEpisodeId to its full Episode (missing entries
        mean Bazarr couldn't report details for that episode)
    """
    details_by_episode: dict[int, "Episode"] = {}
    for series_id in series_ids:
        try:
            eps = await client.list_episodes(seriesid=series_id)
            for ep in eps.data:
                details_by_episode[ep.sonarrEpisodeId] = ep
        except Exception as e:
            logger.warning(
                "Failed to fetch episode details for series %s: %s",
                series_id,
                e,
            )
    return details_by_episode


def _build_language_list(languages: list[Any] | None) -> list[dict]:
    """Build a list of language dictionaries from Bazarr SubtitleLanguage objects.

    Shared by missing_subtitles and audio_language - both use Bazarr's
    {name, code2, code3, forced, hi} shape (audio entries always have
    forced=False, hi=False, matching SubtitleLanguage's defaults).

    Args:
        languages: List of language objects from Bazarr API, or None

    Returns:
        List of dictionaries with language details
    """
    return [
        {
            "name": lang.name,
            "code2": lang.code2,
            "code3": lang.code3,
            "forced": lang.forced,
            "hi": lang.hi,
        }
        for lang in (languages or [])
    ]


async def _upsert_cache_entry(
    db: "AsyncSession",
    cache_id: str,
    kind: str,
    ext_id: int | str,
    title: str,
    media_path: str,
    has_any_subs: bool,
    missing_subtitles: list[Any] | None,
    started_at: datetime,
    audio_language: list[Any] | None = None,
) -> None:
    """Upsert a Bazarr cache entry (select-update/insert pattern).

    Args:
        db: Async database session
        cache_id: Unique cache ID
        kind: "movie" or "episode"
        ext_id: External ID (radarrId or sonarrEpisodeId)
        title: Display title
        media_path: Path to media file
        has_any_subs: Whether the item has any subtitles
        missing_subtitles: List of missing language objects
        started_at: Poll start time
        audio_language: List of audio language objects, if known
    """
    result = await db.execute(select(BazarrCache).where(BazarrCache.id == cache_id))
    existing = result.scalar_one_or_none()

    missing_subs_list = _build_language_list(missing_subtitles)
    audio_lang_list = _build_language_list(audio_language)

    if existing:
        # Update existing record
        existing.title = title
        existing.media_path = media_path
        existing.has_any_subs = has_any_subs
        existing.missing_subtitles = missing_subs_list
        existing.audio_language = audio_lang_list
        existing.last_polled = started_at
    else:
        # Insert new record
        cache_entry = BazarrCache(
            id=cache_id,
            kind=kind,
            ext_id=ext_id,
            title=title,
            media_path=media_path,
            has_any_subs=has_any_subs,
            missing_subtitles=missing_subs_list,
            audio_language=audio_lang_list,
            last_polled=started_at,
            active_job_id=None,
        )
        db.add(cache_entry)

    await db.commit()


async def _process_movie(
    db: "AsyncSession",
    wanted_movie: Any,
    path_map: PathMap,
    started_at: datetime,
    audio_language: list[Any] | None = None,
    media_path_detail: str | None = None,
) -> None:
    """Process a single wanted movie.

    Args:
        db: Async database session
        wanted_movie: WantedMovie from Bazarr API
        path_map: PathMap for path translation
        started_at: Poll start time
        audio_language: Audio languages for this movie, if known (the wanted
            endpoint doesn't carry it; callers batch-fetch it separately)
        media_path_detail: Real media file path for this movie, fetched from
            the full movie details endpoint. The wanted endpoint only
            carries sceneName (often null), so the authoritative path is
            joined in separately. Falls back to sceneName if unavailable.
    """
    # Resolve media_path: prefer the full-detail path (authoritative),
    # fall back to the wanted endpoint's sceneName.
    media_path = media_path_detail or wanted_movie.sceneName or ""
    if media_path:
        media_path = path_map.translate(media_path)

    # Check if this movie has any subtitles at all (no missing subtitles = has all)
    has_any_subs = len(wanted_movie.missing_subtitles or []) == 0

    cache_id = BazarrCache.make_id("movie", wanted_movie.radarrId)

    await _upsert_cache_entry(
        db,
        cache_id,
        "movie",
        wanted_movie.radarrId,
        wanted_movie.title,
        media_path,
        has_any_subs,
        wanted_movie.missing_subtitles,
        started_at,
        audio_language,
    )


async def _process_episode(
    db: "AsyncSession",
    wanted_episode: Any,
    path_map: PathMap,
    started_at: datetime,
    audio_language: list[Any] | None = None,
    media_path_detail: str | None = None,
) -> None:
    """Process a single wanted episode.

    Args:
        db: Async database session
        wanted_episode: WantedEpisode from Bazarr API
        path_map: PathMap for path translation
        started_at: Poll start time
        audio_language: Audio languages for this episode, if known (the
            wanted endpoint doesn't carry it; callers batch-fetch it
            separately)
        media_path_detail: Real media file path for this episode, fetched
            from the full episode details endpoint. The wanted endpoint
            only carries sceneName (often null), so the authoritative path
            is joined in separately. Falls back to sceneName if unavailable.
    """
    # Resolve media_path: prefer the full-detail path (authoritative),
    # fall back to the wanted endpoint's sceneName.
    media_path = media_path_detail or wanted_episode.sceneName or ""
    if media_path:
        media_path = path_map.translate(media_path)

    # Check if this episode has any subtitles at all (no missing subtitles = has all)
    has_any_subs = len(wanted_episode.missing_subtitles or []) == 0

    cache_id = BazarrCache.make_id("episode", wanted_episode.sonarrEpisodeId)

    await _upsert_cache_entry(
        db,
        cache_id,
        "episode",
        wanted_episode.sonarrEpisodeId,
        f"{wanted_episode.seriesTitle} - {wanted_episode.episodeTitle}",
        media_path,
        has_any_subs,
        wanted_episode.missing_subtitles,
        started_at,
        audio_language,
    )


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
                media_path = movie.path or movie.sceneName or ""
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
                        audio_language=_build_language_list(movie.audio_language),
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

    Separates HTTP calls from DB operations to avoid holding DB transactions
    during network I/O (follows short-transaction convention).

    Args:
        db: Async database session
        client: BazarrClient instance
        path_map: PathMap for path translation
        started_at: Poll start time
    """
    try:
        # Phase 1: HTTP calls only - collect cache entries without DB access
        cache_entries_to_add = []

        series_page = await client.list_all_series(length=200)

        for series in series_page.data:
            episodes_page = await client.list_episodes(seriesid=series.sonarrSeriesId)

            for episode in episodes_page.data:
                # Check if episode has no subtitles at all
                if not episode.subtitles:
                    media_path = episode.path or episode.sceneName or ""
                    if media_path:
                        media_path = path_map.translate(media_path)

                    cache_id = BazarrCache.make_id("episode", episode.sonarrEpisodeId)
                    cache_entries_to_add.append(
                        {
                            "cache_id": cache_id,
                            "ext_id": episode.sonarrEpisodeId,
                            "title": f"{series.title} - {episode.title}",
                            "media_path": media_path,
                            "audio_language": _build_language_list(
                                episode.audio_language
                            ),
                        }
                    )

        # Phase 2: DB operations only - upsert all collected entries
        for entry in cache_entries_to_add:
            result = await db.execute(
                select(BazarrCache).where(BazarrCache.id == entry["cache_id"])
            )
            existing = result.scalar_one_or_none()

            if not existing:
                cache_entry = BazarrCache(
                    id=entry["cache_id"],
                    kind="episode",
                    ext_id=entry["ext_id"],
                    title=entry["title"],
                    media_path=entry["media_path"],
                    has_any_subs=False,
                    missing_subtitles=[],  # Empty because we don't know what's missing
                    audio_language=entry["audio_language"],
                    last_polled=started_at,
                    active_job_id=None,
                )
                db.add(cache_entry)

        await db.commit()
    except Exception as e:
        logger.warning("Failed to poll all episodes: %s", e)


async def _delete_stale(
    db: "AsyncSession",
    started_at: datetime,
    poll_movies: bool = True,
    poll_episodes: bool = True,
) -> int:
    """Delete items that are no longer wanted.

    Removes items from cache where last_polled < started_at
    (meaning they were not seen in the current poll cycle).

    Args:
        db: Async database session
        started_at: Poll start time
        poll_movies: Whether movies were polled (delete stale movies if True)
        poll_episodes: Whether episodes were polled (delete stale episodes if True)

    Returns:
        Number of deleted items
    """
    # Only delete items of the types that were actually polled. If neither
    # flag is set, nothing was polled, so delete nothing rather than falling
    # back to an unconditional (both-kinds) delete.
    conditions = []
    if poll_movies:
        conditions.append(BazarrCache.kind == "movie")
    if poll_episodes:
        conditions.append(BazarrCache.kind == "episode")

    if not conditions:
        return 0

    query = delete(BazarrCache).where(
        BazarrCache.last_polled < started_at, or_(*conditions)
    )

    result = await db.execute(query)
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

                client, bazarr_url, bazarr_api_key, bazarr_timeout = (
                    await get_bazarr_client_with_settings(db, settings)
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
