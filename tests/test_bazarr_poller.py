"""Tests for Bazarr poller."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select

from audio_to_subs.bazarr.client import BazarrClient
from audio_to_subs.bazarr.pathmap import PathMap
from audio_to_subs.bazarr.poller import (
    poll_once,
    run_bazarr_poller,
    start_poller,
    stop_poller,
    get_bazarr_client,
    get_path_map,
    get_settings_value,
    get_track_no_subs,
    _process_movie,
    _process_episode,
    _delete_stale,
    _get_poll_interval,
)
from audio_to_subs.db.models import BazarrCache, Setting


class TestGetBazarrClient:
    """Test get_bazarr_client function."""

    @pytest.mark.asyncio
    async def test_get_client_with_config(self):
        """Test getting client with valid config."""
        client = await get_bazarr_client(
            bazarr_url="http://test:6767",
            bazarr_api_key="test-key",
        )
        
        assert client is not None
        assert client.base_url == "http://test:6767"
        assert client.api_key == "test-key"
        
        await client.close()

    @pytest.mark.asyncio
    async def test_get_client_missing_url(self):
        """Test getting client with missing URL."""
        client = await get_bazarr_client(
            bazarr_url=None,
            bazarr_api_key="test-key",
        )
        
        assert client is None

    @pytest.mark.asyncio
    async def test_get_client_missing_api_key(self):
        """Test getting client with missing API key."""
        client = await get_bazarr_client(
            bazarr_url="http://test:6767",
            bazarr_api_key=None,
        )
        
        assert client is None

    @pytest.mark.asyncio
    async def test_get_client_missing_both(self):
        """Test getting client with both missing."""
        client = await get_bazarr_client(
            bazarr_url=None,
            bazarr_api_key=None,
        )
        
        assert client is None


class TestGetPathMap:
    """Test get_path_map function."""

    @pytest.mark.asyncio
    async def test_get_path_map_empty_db(self, mock_db_session):
        """Test get_path_map with empty database."""
        path_map = await get_path_map(mock_db_session)
        
        assert isinstance(path_map, PathMap)
        assert len(path_map.get_mappings()) == 0

    @pytest.mark.asyncio
    async def test_get_path_map_with_settings(self, mock_db_session):
        """Test get_path_map with settings in database."""
        # Create a setting with path mappings
        path_mappings = [
            {"bazarr_prefix": "/bazarr/movies", "local_prefix": "/local/movies"},
        ]
        
        setting = Setting(
            key="path_mappings",
            value_json=json.dumps(path_mappings),
        )
        mock_db_session.add(setting)
        await mock_db_session.commit()
        
        path_map = await get_path_map(mock_db_session)
        
        assert isinstance(path_map, PathMap)
        assert len(path_map.get_mappings()) == 1


class TestGetSettingsValue:
    """Test get_settings_value function."""

    @pytest.mark.asyncio
    async def test_get_settings_value_existing(self, mock_db_session):
        """Test get_settings_value with existing setting."""
        setting = Setting(
            key="test_setting",
            value_json=json.dumps("test_value"),
        )
        mock_db_session.add(setting)
        await mock_db_session.commit()
        
        value = await get_settings_value(mock_db_session, "test_setting", "default")
        
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_get_settings_value_missing(self, mock_db_session):
        """Test get_settings_value with missing setting."""
        value = await get_settings_value(
            mock_db_session, "nonexistent", "default_value"
        )
        
        assert value == "default_value"


class TestGetTrackNoSubs:
    """Test get_track_no_subs function."""

    @pytest.mark.asyncio
    async def test_get_track_no_subs_false(self, mock_db_session):
        """Test get_track_no_subs returns False by default."""
        value = await get_track_no_subs(mock_db_session)
        
        assert value is False

    @pytest.mark.asyncio
    async def test_get_track_no_subs_true(self, mock_db_session):
        """Test get_track_no_subs returns True when set."""
        setting = Setting(
            key="bazarr_track_no_subs",
            value_json=json.dumps(True),
        )
        mock_db_session.add(setting)
        await mock_db_session.commit()
        
        value = await get_track_no_subs(mock_db_session)
        
        assert value is True


class TestProcessMovie:
    """Test _process_movie function."""

    @pytest.mark.asyncio
    async def test_process_movie_new_entry(self, mock_db_session):
        """Test processing a movie creates a new cache entry."""
        # Create a mock wanted movie
        class MockWantedMovie:
            title = "Inception"
            radarrId = 123
            sceneName = "/bazarr/movies/Inception.mkv"
            missing_subtitles = []
        
        mock_movie = MockWantedMovie()
        path_map = PathMap([("/bazarr/movies", "/local/movies")])
        started_at = datetime.now(timezone.utc)
        
        await _process_movie(mock_db_session, mock_movie, path_map, started_at)
        
        # Check that the entry was created
        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "movie:123")
        )
        entry = result.scalar_one_or_none()
        
        assert entry is not None
        assert entry.kind == "movie"
        assert entry.ext_id == 123
        assert entry.title == "Inception"
        # Path should be translated
        assert "/local/movies" in entry.media_path

    @pytest.mark.asyncio
    async def test_process_movie_update_existing(self, mock_db_session):
        """Test processing a movie updates existing cache entry."""
        # Create existing entry
        existing = BazarrCache(
            id="movie:123",
            kind="movie",
            ext_id=123,
            title="Old Title",
            media_path="/old/path.mkv",
            has_any_subs=False,
            missing_subtitles=[],
            last_polled=datetime.now(timezone.utc) - timedelta(days=1),
        )
        mock_db_session.add(existing)
        await mock_db_session.commit()
        
        # Create a mock wanted movie with updated info
        class MockWantedMovie:
            title = "New Title"
            radarrId = 123
            sceneName = "/bazarr/movies/NewTitle.mkv"
            missing_subtitles = []
        
        mock_movie = MockWantedMovie()
        path_map = PathMap([("/bazarr/movies", "/local/movies")])
        started_at = datetime.now(timezone.utc)
        
        await _process_movie(mock_db_session, mock_movie, path_map, started_at)
        
        # Check that the entry was updated
        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "movie:123")
        )
        entry = result.scalar_one_or_none()
        
        assert entry is not None
        assert entry.title == "New Title"
        assert "/local/movies/NewTitle.mkv" in entry.media_path


class TestProcessEpisode:
    """Test _process_episode function."""

    @pytest.mark.asyncio
    async def test_process_episode_new_entry(self, mock_db_session):
        """Test processing an episode creates a new cache entry."""
        # Create a mock wanted episode
        class MockSubtitleLanguage:
            name = "English"
            code2 = "en"
            code3 = "eng"
            forced = False
            hi = False
        
        class MockWantedEpisode:
            seriesTitle = "Test Show"
            episodeTitle = "Pilot"
            episode_number = "1x01"
            sonarrEpisodeId = 456
            sonarrSeriesId = 789
            sceneName = "/bazarr/tv/Test Show/Pilot.mkv"
            missing_subtitles = [MockSubtitleLanguage()]
            tags = []
            seriesType = "standard"
        
        mock_episode = MockWantedEpisode()
        path_map = PathMap([("/bazarr/tv", "/local/tv")])
        started_at = datetime.now(timezone.utc)
        
        await _process_episode(mock_db_session, mock_episode, path_map, started_at)
        
        # Check that the entry was created
        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "episode:456")
        )
        entry = result.scalar_one_or_none()
        
        assert entry is not None
        assert entry.kind == "episode"
        assert entry.ext_id == 456
        assert "Test Show - Pilot" in entry.title


class TestDeleteStale:
    """Test _delete_stale function."""

    @pytest.mark.asyncio
    async def test_delete_stale_removes_old_entries(self, mock_db_session):
        """Test that stale entries are deleted."""
        # Create old entries
        old_time = datetime.now(timezone.utc) - timedelta(days=1)
        
        old_entry1 = BazarrCache(
            id="movie:1",
            kind="movie",
            ext_id=1,
            title="Old Movie",
            media_path="/path.mkv",
            has_any_subs=False,
            missing_subtitles=[],
            last_polled=old_time,
        )
        old_entry2 = BazarrCache(
            id="movie:2",
            kind="movie",
            ext_id=2,
            title="Another Old Movie",
            media_path="/path2.mkv",
            has_any_subs=False,
            missing_subtitles=[],
            last_polled=old_time,
        )
        mock_db_session.add_all([old_entry1, old_entry2])
        await mock_db_session.commit()
        
        # Delete stale entries
        started_at = datetime.now(timezone.utc)
        deleted_count = await _delete_stale(mock_db_session, started_at)
        
        assert deleted_count == 2

    @pytest.mark.asyncio
    async def test_delete_stale_keeps_recent_entries(self, mock_db_session):
        """Test that entries polled AFTER started_at are kept."""
        # started_at is set in the past so that recent_entry.last_polled > started_at.
        started_at = datetime.now(timezone.utc) - timedelta(seconds=5)

        recent_entry = BazarrCache(
            id="movie:3",
            kind="movie",
            ext_id=3,
            title="Recent Movie",
            media_path="/path.mkv",
            has_any_subs=False,
            missing_subtitles=[],
            last_polled=datetime.now(timezone.utc),  # after started_at
        )
        mock_db_session.add(recent_entry)
        await mock_db_session.commit()

        deleted_count = await _delete_stale(mock_db_session, started_at)

        assert deleted_count == 0


class TestGetPollInterval:
    """Test _get_poll_interval function."""

    @pytest.mark.asyncio
    async def test_get_poll_interval_default(self, mock_db_session):
        """Test get_poll_interval returns default value."""
        interval = await _get_poll_interval(mock_db_session)
        
        assert interval == 3600

    @pytest.mark.asyncio
    async def test_get_poll_interval_custom(self, mock_db_session):
        """Test get_poll_interval returns custom value."""
        setting = Setting(
            key="bazarr_poll_interval",
            value_json=json.dumps(7200),
        )
        mock_db_session.add(setting)
        await mock_db_session.commit()
        
        interval = await _get_poll_interval(mock_db_session)
        
        assert interval == 7200


class TestPollerIntegration:
    """Integration tests for poller."""

    @pytest.mark.asyncio
    async def test_poll_once_with_mock_client(self, mock_db_session):
        """Test poll_once with a mock client."""
        # Create mock client
        mock_client = AsyncMock(spec=BazarrClient)
        
        # Mock empty responses
        mock_client.list_wanted_movies.return_value = AsyncMock()
        mock_client.list_wanted_movies.return_value.data = []
        mock_client.list_wanted_movies.return_value.total = 0
        
        mock_client.list_wanted_episodes.return_value = AsyncMock()
        mock_client.list_wanted_episodes.return_value.data = []
        mock_client.list_wanted_episodes.return_value.total = 0
        
        path_map = PathMap()
        
        # Call poll_once
        processed = await poll_once(mock_db_session, mock_client, path_map)
        
        assert processed == 0
        mock_client.list_wanted_movies.assert_awaited_once()
        mock_client.list_wanted_episodes.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_poller(self):
        """Test start_poller function."""
        mock_app = Mock()
        mock_app.state = Mock()
        mock_app.state.shutdown = asyncio.Event()
        mock_app.state.poller_task = None
        
        await start_poller(mock_app)
        
        assert mock_app.state.poller_task is not None

    @pytest.mark.asyncio
    async def test_stop_poller(self):
        """Test stop_poller cancels the running task and clears the state."""
        mock_app = Mock()
        mock_app.state = Mock()

        # Use a real asyncio task so stop_poller can call .cancel() and await it.
        async def _dummy():
            await asyncio.sleep(10)

        task = asyncio.create_task(_dummy())
        mock_app.state.poller_task = task

        await stop_poller(mock_app)

        assert task.cancelled()
        assert mock_app.state.poller_task is None

    @pytest.mark.asyncio
    async def test_run_bazarr_poller_exits_when_shutdown_set(self):
        """run_bazarr_poller must return promptly when shutdown is already set.

        Before the fix, run_bazarr_poller checked app.state.shutdown at the top
        of its loop and raised AttributeError because the lifespan never created
        the event.  After the fix the function reads the event, sees it is set,
        and returns immediately.
        """
        mock_app = Mock()
        mock_app.state = Mock()
        mock_app.state.shutdown = asyncio.Event()
        mock_app.state.shutdown.set()  # already shut down

        # Should return in well under 2 seconds; if it hangs the fix is broken.
        await asyncio.wait_for(run_bazarr_poller(mock_app), timeout=2.0)

    @pytest.mark.asyncio
    async def test_run_bazarr_poller_wait_for_no_suppress_timeout_kwarg(self):
        """The interval wait inside run_bazarr_poller must not raise TypeError.

        Before the fix, asyncio.wait_for was called with suppress_timeout=True
        which is not a valid kwarg and raises TypeError immediately after the
        first Bazarr-not-configured sleep attempt.
        After the fix the interval wait uses try/except asyncio.TimeoutError.
        """
        mock_app = Mock()
        mock_app.state = Mock()
        mock_app.state.shutdown = asyncio.Event()

        # Signal shutdown after a short delay so the poller exercises the
        # wait_for path (Bazarr not configured → interval wait) at least once.
        async def _trigger():
            await asyncio.sleep(0.2)
            mock_app.state.shutdown.set()

        asyncio.create_task(_trigger())

        # Patch the DB session so the poller can get the interval without a DB.
        with patch(
            "audio_to_subs.bazarr.poller._get_poll_interval",
            new=AsyncMock(return_value=60),
        ):
            # TypeError from suppress_timeout=True would propagate here and fail.
            await asyncio.wait_for(run_bazarr_poller(mock_app), timeout=3.0)

    @pytest.mark.asyncio
    async def test_poller_releases_session_before_sleep(self):
        """Regression: DB session must exit before the inter-poll wait.

        Before the fix, the asyncio.wait_for sleep (when Bazarr is not
        configured) ran inside the async-with get_async_session() block.
        This held a BEGIN IMMEDIATE write lock for the full poll interval
        (default 3600 s), blocking every other writer (reaper, health check).
        """
        mock_app = Mock()
        mock_app.state = Mock()
        mock_app.state.shutdown = asyncio.Event()
        lifecycle: list[str] = []

        @asynccontextmanager
        async def _tracked_session(_url: str):
            lifecycle.append("enter")
            yield Mock()
            lifecycle.append("exit")

        async def _tracked_wait_for(coro, timeout):
            lifecycle.append(f"wait:{int(timeout)}")
            # Trigger shutdown so the poller terminates after one iteration.
            mock_app.state.shutdown.set()
            await asyncio.wait_for(coro, timeout=1.0)

        with (
            patch("audio_to_subs.bazarr.poller.get_async_session", _tracked_session),
            patch(
                "audio_to_subs.bazarr.poller._get_poll_interval",
                new=AsyncMock(return_value=3600),
            ),
            patch(
                "audio_to_subs.bazarr.poller.get_bazarr_client",
                new=AsyncMock(return_value=None),
            ),
            patch("audio_to_subs.bazarr.poller.asyncio.wait_for", _tracked_wait_for),
        ):
            await asyncio.wait_for(run_bazarr_poller(mock_app), timeout=5.0)

        exit_idx = lifecycle.index("exit")
        wait_idx = next(i for i, e in enumerate(lifecycle) if e.startswith("wait:3600"))
        assert exit_idx < wait_idx, (
            f"Session must close before the inter-poll sleep; lifecycle={lifecycle}"
        )
