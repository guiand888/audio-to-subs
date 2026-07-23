"""Bazarr poller for caching the full library's subtitle state.

Periodically polls the entire Bazarr library (movies + episodes) and
updates the local cache with each item's real has_any_subs/missing_subtitles
state, so the Wanted API can serve any display scope (all/missing/no_subs)
without re-polling.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, or_, select

from audio_to_subs.bazarr.client import BazarrClient
from audio_to_subs.bazarr.pathmap import PathMap
from audio_to_subs.db.job_logs import write_job_log
from audio_to_subs.db.models import BazarrCache, LogLevel

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from audio_to_subs.api.settings import Settings
    from audio_to_subs.bazarr.schemas import Episode, Movie

logger = logging.getLogger(__name__)


class ProgressReporter:
    """Tracks refresh progress and emits throttled updates to a callback.

    The full-library sync fetches movies in a single call, so its total is
    known up front (Bazarr's ``/api/movies`` response carries a ``total``).
    Episodes are walked series-by-series (Bazarr has no single "all
    episodes" endpoint), so their count is only known once fully iterated.
    To keep a single coherent progress signal, we start with the known
    movies total and, once that is exhausted, fall back to a live
    "processed" counter with no denominator for the episodes portion.

    Updates are throttled (~1 Hz) so a fast poll loop doesn't flood the
    downstream pub/sub channel.
    """

    def __init__(
        self,
        callback: (
            Callable[[int, int | None, int, str], Coroutine[Any, Any, None]] | None
        ) = None,
        *,
        throttle_seconds: float = 1.0,
    ) -> None:
        self._callback = callback
        self._throttle = throttle_seconds
        self._processed = 0
        self._known_total: int | None = 0
        self._stage = "starting"
        self._last_emit = 0.0

    def set_known_total(self, total: int) -> None:
        """Set the denominator known up front (e.g. the movies total)."""
        self._known_total = total

    def set_stage(self, stage: str) -> None:
        self._stage = stage

    def increment(self, by: int = 1) -> None:
        self._processed += by

    async def step(self, by: int = 1) -> None:
        """Increment processed count and emit a (throttled) progress update.

        Safe to call unconditionally; no-ops when no callback is configured.
        """
        self.increment(by)
        await self.report()

    @property
    def processed(self) -> int:
        return self._processed

    @property
    def total(self) -> int | None:
        # Only report a denominator while the known (movies) portion is being
        # processed. Once we move into the unknown-total episodes tail,
        # report None so the UI shows a live counter instead of a fake
        # estimate.
        if self._known_total and self._processed <= self._known_total:
            return self._known_total
        return None

    @property
    def percent(self) -> int:
        total = self.total
        if not total:
            return 0
        return min(100, round(self._processed / total * 100))

    async def report(self, *, force: bool = False) -> None:
        if self._callback is None:
            return
        now = time.monotonic()
        if not force and (now - self._last_emit) < self._throttle:
            return
        self._last_emit = now
        await self._callback(self._processed, self.total, self.percent, self._stage)


class PollerState:
    """State for the Bazarr poller."""

    def __init__(self) -> None:
        self.shutdown = asyncio.Event()
        self.poll_task: asyncio.Task[Any] | None = None


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


async def poll_once(
    db: "AsyncSession",
    client: BazarrClient,
    path_map: PathMap,
) -> int:
    """Perform a single scheduled full-library poll of all Bazarr items.

    Fetches every movie and episode from Bazarr (not just Bazarr's "wanted"
    subset), translates paths, and updates the bazarr_cache table.

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


# Serializes full-library Bazarr syncs: the periodic poller (poll_once) and
# on-demand manual refreshes (the Wanted page's Refresh button) both call
# poll_bazarr_manually. Without this, two concurrent full syncs each issue
# thousands of short read/write transactions against the same SQLite file
# and can exceed busy_timeout, raising "database is locked" - which aborts
# the refresh and can collaterally starve the worker's own job-claiming
# query on the same file. At most one full sync now runs at a time; a
# second caller waits for the lock instead of racing the DB.
_full_sync_lock = asyncio.Lock()


async def poll_bazarr_manually(
    db: "AsyncSession",
    client: BazarrClient,
    path_map: PathMap,
    item_type: str | None = None,
    reporter: ProgressReporter | None = None,
) -> tuple[int, int]:
    """Perform a full-library poll of Bazarr items, optionally scoped by type.

    Used both for the scheduled background poll (via poll_once, item_type="all")
    and for on-demand manual refreshes triggered from the API. Ingests every
    movie/episode within the active item_type - not just Bazarr's "wanted"
    (missing-subtitle) subset - persisting each item's real
    has_any_subs/missing_subtitles so the Wanted API can serve the
    all/missing/no_subs display scopes without a further poll. Returns
    separate counts for movies and episodes processed.

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
        reporter: Optional progress reporter. A no-op reporter is used when
            None so callers don't need to guard every progress call.

    Returns:
        Tuple of (movies_processed, episodes_processed) counts
    """
    if reporter is None:
        reporter = ProgressReporter()

    if _full_sync_lock.locked():
        logger.info(
            "Waiting for an in-progress Bazarr sync to finish before starting "
            "(item_type=%s)",
            item_type,
        )
        reporter.set_stage("waiting for another sync to finish")
        await reporter.report(force=True)

    async with _full_sync_lock:
        started_at = datetime.now(timezone.utc)
        logger.info(
            "Starting Bazarr poll at %s (item_type=%s)",
            started_at.isoformat(),
            item_type,
        )

        movies_processed = 0
        episodes_processed = 0

        try:
            # Determine which types to poll
            poll_movies = (
                item_type is None or item_type == "all" or item_type == "movie"
            )
            poll_episodes = (
                item_type is None or item_type == "all" or item_type == "episode"
            )

            reporter.set_stage("syncing library")
            await reporter.report(force=True)

            if poll_movies:
                movies_processed = await _poll_all_movies(
                    db, client, path_map, started_at, reporter
                )

            if poll_episodes:
                episodes_processed = await _poll_all_episodes(
                    db, client, path_map, started_at, reporter
                )

            # Delete stale items (no longer present in Bazarr) - only for
            # types that were actually polled
            deleted_count = await _delete_stale(
                db, started_at, poll_movies, poll_episodes
            )
            if deleted_count > 0:
                logger.info("Deleted %d stale items from cache", deleted_count)

            reporter.set_stage("done")
            await reporter.report(force=True)

            logger.info(
                "Bazarr poll complete: processed %d movies, %d episodes, "
                "deleted %d stale",
                movies_processed,
                episodes_processed,
                deleted_count,
            )
            await write_job_log(
                db,
                LogLevel.INFO,
                f"Bazarr sync completed: {movies_processed} movies, "
                f"{episodes_processed} episodes processed, {deleted_count} stale removed",
            )

        except Exception as e:
            logger.error("Error during Bazarr poll: %s", e, exc_info=True)
            await write_job_log(db, LogLevel.ERROR, f"Bazarr sync failed: {e}")
            reporter.set_stage("error")
            await reporter.report(force=True)
            raise

        return movies_processed, episodes_processed


def _build_language_list(languages: list[Any] | None) -> list[dict[str, Any]]:
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
    movie: "Movie",
    path_map: PathMap,
    started_at: datetime,
) -> None:
    """Process a single movie from Bazarr's full `/api/movies` listing.

    Args:
        db: Async database session
        movie: Movie from Bazarr's full movies listing - carries its own
            audio_language, path, subtitles (present files), and
            missing_subtitles, so no separate detail fetch is needed.
        path_map: PathMap for path translation
        started_at: Poll start time
    """
    # Resolve media_path: prefer the authoritative `path` field, fall back to
    # sceneName (often null).
    media_path = movie.path or movie.sceneName or ""
    if media_path:
        media_path = path_map.translate(media_path)

    # Whether this movie actually has any subtitle file present, from the
    # `subtitles` list of files actually on disk (distinct from
    # `missing_subtitles`, which only reports what's absent). A movie can be
    # missing one language while already having a subtitle for another.
    has_any_subs = len(movie.subtitles) > 0

    cache_id = BazarrCache.make_id("movie", movie.radarrId)

    await _upsert_cache_entry(
        db,
        cache_id,
        "movie",
        movie.radarrId,
        movie.title,
        media_path,
        has_any_subs,
        movie.missing_subtitles,
        started_at,
        movie.audio_language,
    )


async def _process_episode(
    db: "AsyncSession",
    episode: "Episode",
    path_map: PathMap,
    started_at: datetime,
    title: str,
) -> None:
    """Process a single episode from Bazarr's full `/api/episodes` listing.

    Args:
        db: Async database session
        episode: Episode from Bazarr's full episodes listing - carries its
            own audio_language, path, subtitles (present files), and
            missing_subtitles, so no separate detail fetch is needed.
        path_map: PathMap for path translation
        started_at: Poll start time
        title: Display title ("<series title> - <episode title>"), composed
            by the caller since a per-episode payload doesn't carry its
            series' title.
    """
    # Resolve media_path: prefer the authoritative `path` field, fall back to
    # sceneName (often null).
    media_path = episode.path or episode.sceneName or ""
    if media_path:
        media_path = path_map.translate(media_path)

    # Whether this episode actually has any subtitle file present, from the
    # `subtitles` list of files actually on disk (distinct from
    # `missing_subtitles`, which only reports what's absent). An episode can
    # be missing one language while already having a subtitle for another.
    has_any_subs = len(episode.subtitles) > 0

    cache_id = BazarrCache.make_id("episode", episode.sonarrEpisodeId)

    await _upsert_cache_entry(
        db,
        cache_id,
        "episode",
        episode.sonarrEpisodeId,
        title,
        media_path,
        has_any_subs,
        episode.missing_subtitles,
        started_at,
        episode.audio_language,
    )


async def _poll_all_movies(
    db: "AsyncSession",
    client: BazarrClient,
    path_map: PathMap,
    started_at: datetime,
    reporter: ProgressReporter | None = None,
) -> int:
    """Fetch and upsert every movie in the Bazarr library (full sync).

    Ingests ALL movies regardless of subtitle state - both fully-subtitled
    and missing/no-subs items - so the cache carries enough state to serve
    every Wanted display scope (all/missing/no_subs) without re-polling.

    This is now the primary (only) source of movie data for a poll, so a
    fetch failure here is NOT swallowed - it propagates to the caller
    (`poll_bazarr_manually`'s outer handler logs it and re-raises), matching
    the pre-M8 behaviour where a failed wanted-movies fetch also propagated
    rather than being silently reported as a successful empty poll.

    Args:
        db: Async database session
        client: BazarrClient instance
        path_map: PathMap for path translation
        started_at: Poll start time
        reporter: Optional progress reporter. `/api/movies` reports an exact
            total up front, seeded here as the known denominator.

    Returns:
        Number of movies processed during this pass.
    """
    processed = 0
    movies_page = await client.list_all_movies()
    if reporter is not None:
        reporter.set_known_total(movies_page.total)
        reporter.set_stage("syncing movies")
        await reporter.report(force=True)

    for movie in movies_page.data:
        await _process_movie(db, movie, path_map, started_at)
        processed += 1
        if reporter is not None:
            await reporter.step()

    return processed


# Number of series batched into a single `/api/episodes?seriesid[]=...` call.
# Bazarr's endpoint has no pagination and answers any-sized `seriesid[]` list
# with one `IN (...)` query, so batching trades one HTTP round-trip per
# series for one per batch. 100 keeps the query string comfortably under
# typical proxy/header size limits while still cutting a few-hundred-series
# library down to a handful of requests.
EPISODE_BATCH_SIZE = 100


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    """Split `items` into consecutive chunks of at most `size` elements."""
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _poll_all_episodes(
    db: "AsyncSession",
    client: BazarrClient,
    path_map: PathMap,
    started_at: datetime,
    reporter: ProgressReporter | None = None,
) -> int:
    """Fetch and upsert every episode in the Bazarr library (full sync).

    Ingests ALL episodes regardless of subtitle state, walking series in
    batches since Bazarr has no single "all episodes" endpoint (bounded by
    the number of batches, not one call per series or per episode - see
    `EPISODE_BATCH_SIZE`).

    Each episode is upserted immediately as it's fetched rather than
    collected into a separate DB phase: `_upsert_cache_entry` opens and
    commits its own short transaction per item (select + commit), so no
    write transaction is ever held open across the next batch's HTTP call
    (short-transaction convention).

    A failure listing the series themselves propagates (this is now the
    primary source of episode data - see `_poll_all_movies`'s docstring).
    A failure fetching one batch's episodes is tolerated - logged and
    skipped - so one bad batch doesn't abort the sync for every other
    series, mirroring the old per-series detail-fetch tolerance.

    Args:
        db: Async database session
        client: BazarrClient instance
        path_map: PathMap for path translation
        started_at: Poll start time
        reporter: Optional progress reporter. Bazarr has no upfront total
            for episodes (only known after walking every series), so this
            pass never sets a known total - the reporter falls back to a
            live "processed" counter for it. A heartbeat is forced once per
            batch so a slow/large library still emits progress regularly
            rather than going silent for the whole episodes phase.

    Returns:
        Number of episodes processed during this pass.
    """
    processed = 0
    series_page = await client.list_all_series()
    series_by_id = {series.sonarrSeriesId: series for series in series_page.data}

    if reporter is not None:
        reporter.set_stage("syncing episodes")
        await reporter.report(force=True)

    for batch in _chunked(series_page.data, EPISODE_BATCH_SIZE):
        series_ids = [series.sonarrSeriesId for series in batch]
        try:
            episodes_page = await client.list_episodes(seriesid=series_ids)
        except Exception as e:
            logger.warning(
                "Failed to fetch episodes for series batch %s: %s",
                series_ids,
                e,
            )
            continue

        if reporter is not None:
            # Heartbeat right after the (potentially slow) batch call
            # returns, independent of the throttled per-item stepping below -
            # bounds the max silent gap to one batch instead of one series.
            await reporter.report(force=True)

        for episode in episodes_page.data:
            series = series_by_id.get(episode.sonarrSeriesId)
            series_title = series.title if series is not None else "Unknown series"
            title = f"{series_title} - {episode.title}"
            await _process_episode(db, episode, path_map, started_at, title)
            processed += 1
            if reporter is not None:
                await reporter.step()

    return processed


async def _delete_stale(
    db: "AsyncSession",
    started_at: datetime,
    poll_movies: bool = True,
    poll_episodes: bool = True,
) -> int:
    """Delete items no longer present in Bazarr's library.

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
    return int(await get_settings_value(db, "bazarr_poll_interval", 3600))


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
