"""Tests for Bazarr poller."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select

from audio_to_subs.bazarr.client import BazarrClient
from audio_to_subs.bazarr.pathmap import PathMap
from audio_to_subs.bazarr.poller import (
    _delete_stale,
    _get_poll_interval,
    _poll_all_episodes,
    _process_episode,
    _process_movie,
    get_bazarr_client,
    get_bazarr_client_with_settings,
    get_path_map,
    get_settings_value,
    get_track_no_subs,
    poll_once,
    run_bazarr_poller,
    start_poller,
    stop_poller,
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
    async def test_get_client_with_timeout(self):
        """Test getting client with custom timeout."""
        client = await get_bazarr_client(
            bazarr_url="http://test:6767",
            bazarr_api_key="test-key",
            bazarr_timeout=60.0,
        )

        assert client is not None
        assert client.base_url == "http://test:6767"
        assert client.api_key == "test-key"
        # Note: timeout is stored in the client but not directly accessible

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


class TestGetBazarrClientWithSettings:
    """Test get_bazarr_client_with_settings function."""

    @pytest.mark.asyncio
    async def test_get_client_with_database_settings(self, mock_db_session):
        """Test getting client with database settings."""
        # Set up database settings
        db_settings = [
            Setting(key="bazarr_url", value_json=json.dumps("http://db-bazarr:6767")),
            Setting(key="bazarr_api_key", value_json=json.dumps("db-api-key")),
            Setting(key="bazarr_timeout", value_json=json.dumps(60.0)),
        ]
        for setting in db_settings:
            mock_db_session.add(setting)
        await mock_db_session.commit()

        client, url, api_key, timeout = await get_bazarr_client_with_settings(
            mock_db_session
        )

        assert client is not None
        assert client.base_url == "http://db-bazarr:6767"
        assert client.api_key == "db-api-key"
        assert url == "http://db-bazarr:6767"
        assert api_key == "db-api-key"
        assert timeout == 60.0

        await client.close()

    @pytest.mark.asyncio
    async def test_get_client_fallback_to_env_settings(self, mock_db_session):
        """Test getting client falls back to environment settings when database is empty."""
        # Create mock environment settings
        from audio_to_subs.api.settings import Settings

        mock_env_settings = Settings(
            BAZARR_URL="http://env-bazarr:6767",
            BAZARR_API_KEY="env-api-key",
            BAZARR_TIMEOUT=90.0,
        )

        client, url, api_key, timeout = await get_bazarr_client_with_settings(
            mock_db_session, mock_env_settings
        )

        assert client is not None
        assert client.base_url == "http://env-bazarr:6767"
        assert client.api_key == "env-api-key"
        assert url == "http://env-bazarr:6767"
        assert api_key == "env-api-key"
        assert timeout == 90.0

        await client.close()

    @pytest.mark.asyncio
    async def test_get_client_database_priority_over_env(self, mock_db_session):
        """Test that database settings take priority over environment settings."""
        # Set up database settings
        db_settings = [
            Setting(key="bazarr_url", value_json=json.dumps("http://db-bazarr:6767")),
            Setting(key="bazarr_api_key", value_json=json.dumps("db-api-key")),
            Setting(key="bazarr_timeout", value_json=json.dumps(60.0)),
        ]
        for setting in db_settings:
            mock_db_session.add(setting)
        await mock_db_session.commit()

        # Create mock environment settings with different values
        from audio_to_subs.api.settings import Settings

        mock_env_settings = Settings(
            BAZARR_URL="http://env-bazarr:6767",  # Should be ignored
            BAZARR_API_KEY="env-api-key",  # Should be ignored
            BAZARR_TIMEOUT=90.0,  # Should be ignored
        )

        client, url, api_key, timeout = await get_bazarr_client_with_settings(
            mock_db_session, mock_env_settings
        )

        assert client is not None
        assert client.base_url == "http://db-bazarr:6767"  # DB takes priority
        assert client.api_key == "db-api-key"  # DB takes priority
        assert url == "http://db-bazarr:6767"
        assert api_key == "db-api-key"
        assert timeout == 60.0  # DB takes priority

        await client.close()

    @pytest.mark.asyncio
    async def test_get_client_empty_string_url_no_fallback(self, mock_db_session):
        """Test that empty string URL in DB does NOT fall back to env (sentinel fix)."""
        # Set DB setting to empty string (user explicitly cleared it)
        db_settings = [
            Setting(key="bazarr_url", value_json=json.dumps("")),
            Setting(key="bazarr_api_key", value_json=json.dumps("db-api-key")),
        ]
        for setting in db_settings:
            mock_db_session.add(setting)
        await mock_db_session.commit()

        # Create mock environment settings with non-empty values
        from audio_to_subs.api.settings import Settings

        mock_env_settings = Settings(
            BAZARR_URL="http://env-bazarr:6767",  # Should NOT be used
            BAZARR_API_KEY="env-api-key",
        )

        client, url, api_key, timeout = await get_bazarr_client_with_settings(
            mock_db_session, mock_env_settings
        )

        # Client should be None because URL is empty string (falsy but explicitly set)
        assert client is None
        assert url == ""  # Empty string from DB, not env fallback

    @pytest.mark.asyncio
    async def test_get_client_timeout_30_no_fallback(self, mock_db_session):
        """Test that timeout=30.0 in DB does NOT fall back to env (sentinel fix)."""
        # Set DB setting to 30.0 (the default value)
        db_settings = [
            Setting(key="bazarr_url", value_json=json.dumps("http://db-bazarr:6767")),
            Setting(key="bazarr_api_key", value_json=json.dumps("db-api-key")),
            Setting(key="bazarr_timeout", value_json=json.dumps(30.0)),
        ]
        for setting in db_settings:
            mock_db_session.add(setting)
        await mock_db_session.commit()

        # Create mock environment settings with different timeout
        from audio_to_subs.api.settings import Settings

        mock_env_settings = Settings(
            BAZARR_URL="http://db-bazarr:6767",
            BAZARR_API_KEY="db-api-key",
            BAZARR_TIMEOUT=90.0,  # Should NOT be used
        )

        client, url, api_key, timeout = await get_bazarr_client_with_settings(
            mock_db_session, mock_env_settings
        )

        assert client is not None
        assert timeout == 30.0  # DB value, not env fallback

        await client.close()

    @pytest.mark.asyncio
    async def test_get_client_seeded_null_falls_back_to_env(self, mock_db_session):
        """Test that seeded DEFAULT_SETTINGS rows (JSON null) still fall back to env.

        Reproduces the scenario created by `_seed_default_settings`, which is
        called on every `GET /api/settings` and inserts a row for every key in
        DEFAULT_SETTINGS -- including bazarr_url=None and bazarr_api_key=None --
        the first time the settings table is empty. Before the fix, a DB row
        holding JSON `null` decoded to a real `None`, which was indistinguishable
        from an explicit "disable Bazarr" and therefore never fell back to env.

        bazarr_timeout is seeded to a real value (30.0, DEFAULT_SETTINGS'
        default), not None, so it's correctly treated as explicitly set and
        stays sticky -- only bazarr_url/bazarr_api_key (seeded as None) should
        fall back to env here.
        """
        from audio_to_subs.api.routes.settings import DEFAULT_SETTINGS

        for key, value in DEFAULT_SETTINGS.items():
            mock_db_session.add(Setting(key=key, value_json=json.dumps(value)))
        await mock_db_session.commit()

        from audio_to_subs.api.settings import Settings

        mock_env_settings = Settings(
            BAZARR_URL="http://env-bazarr:6767",
            BAZARR_API_KEY="env-api-key",
            BAZARR_TIMEOUT=45.0,
        )

        client, url, api_key, timeout = await get_bazarr_client_with_settings(
            mock_db_session, mock_env_settings
        )

        assert client is not None
        assert url == "http://env-bazarr:6767"
        assert api_key == "env-api-key"
        assert timeout == 30.0  # seeded DB value, not env fallback

        await client.close()


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

    @pytest.mark.asyncio
    async def test_process_movie_stores_audio_language(self, mock_db_session):
        """audio_language, when passed, is stored on the cache row - it's
        never present on the wanted-movie object itself (Bazarr's wanted
        endpoint doesn't carry it), so callers must fetch and pass it in."""

        class MockAudioLanguage:
            name = "French"
            code2 = "fr"
            code3 = "fre"
            forced = False
            hi = False

        class MockWantedMovie:
            title = "French Film"
            radarrId = 321
            sceneName = "/bazarr/movies/French Film.mkv"
            missing_subtitles = []

        mock_movie = MockWantedMovie()
        path_map = PathMap()
        started_at = datetime.now(timezone.utc)

        await _process_movie(
            mock_db_session,
            mock_movie,
            path_map,
            started_at,
            [MockAudioLanguage()],
        )

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "movie:321")
        )
        entry = result.scalar_one_or_none()

        assert entry is not None
        assert entry.audio_language == [
            {
                "name": "French",
                "code2": "fr",
                "code3": "fre",
                "forced": False,
                "hi": False,
            }
        ]

    @pytest.mark.asyncio
    async def test_process_movie_no_audio_language_defaults_to_empty(
        self, mock_db_session
    ):
        """When Bazarr can't report an audio language, the cache stores []
        (not None) - this is what drives the frontend's Auto-only dropdown."""

        class MockWantedMovie:
            title = "Unknown Audio Film"
            radarrId = 322
            sceneName = "/bazarr/movies/Unknown.mkv"
            missing_subtitles = []

        mock_movie = MockWantedMovie()
        path_map = PathMap()
        started_at = datetime.now(timezone.utc)

        await _process_movie(mock_db_session, mock_movie, path_map, started_at)

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "movie:322")
        )
        entry = result.scalar_one_or_none()

        assert entry is not None
        assert entry.audio_language == []

    @pytest.mark.asyncio
    async def test_process_movie_prefers_detail_path_over_sceneName(
        self, mock_db_session
    ):
        """The wanted endpoint's sceneName is often null in real Bazarr; the
        authoritative media path comes from the full movie details endpoint.
        media_path_detail must win over sceneName when both are present."""

        class MockWantedMovie:
            title = "Inception"
            radarrId = 700
            sceneName = "Inception.2010.1080p.BluRay.x264-GROUP"
            missing_subtitles = []

        mock_movie = MockWantedMovie()
        path_map = PathMap([("/bazarr/movies", "/local/movies")])
        started_at = datetime.now(timezone.utc)

        await _process_movie(
            mock_db_session,
            mock_movie,
            path_map,
            started_at,
            media_path_detail="/bazarr/movies/Inception (2010)/Inception.mkv",
        )

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "movie:700")
        )
        entry = result.scalar_one()
        # The full-detail path was translated and stored, not the sceneName.
        assert entry.media_path == "/local/movies/Inception (2010)/Inception.mkv"

    @pytest.mark.asyncio
    async def test_process_movie_null_sceneName_uses_detail_path(self, mock_db_session):
        """Mirrors the real-world bug: the wanted endpoint returns
        sceneName=None and the cache must still get a usable media_path
        from the joined-in full-detail path."""

        class MockWantedMovie:
            title = "The Players"
            radarrId = 701
            sceneName = None
            missing_subtitles = []

        mock_movie = MockWantedMovie()
        path_map = PathMap()
        started_at = datetime.now(timezone.utc)

        await _process_movie(
            mock_db_session,
            mock_movie,
            path_map,
            started_at,
            media_path_detail="/movies/The Players (2012)/The Players 720p H264.mkv",
        )

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "movie:701")
        )
        entry = result.scalar_one()
        assert entry.media_path == (
            "/movies/The Players (2012)/The Players 720p H264.mkv"
        )

    @pytest.mark.asyncio
    async def test_process_movie_has_any_subs_from_present_subtitles(
        self, mock_db_session
    ):
        """has_any_subs reflects PRESENT subtitle files, not the missing list (B10).

        Mirrors the episode case: a movie still wanted for English but already
        carrying a French subtitle file must report has_any_subs=True.
        """

        class MockSubtitle:
            name = "French"
            code2 = "fr"
            code3 = "fre"
            forced = False
            hi = False

        class MockWantedMovie:
            title = "Mixed Movie"
            radarrId = 4242
            sceneName = "/bazarr/movies/Mixed Movie.mkv"
            missing_subtitles = [MockSubtitle()]  # still missing English...

        mock_movie = MockWantedMovie()
        path_map = PathMap()
        started_at = datetime.now(timezone.utc)

        await _process_movie(
            mock_db_session,
            mock_movie,
            path_map,
            started_at,
            subtitles=[MockSubtitle()],  # ...but a French sub file is present
        )

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "movie:4242")
        )
        entry = result.scalar_one_or_none()

        assert entry is not None
        assert entry.has_any_subs is True

    @pytest.mark.asyncio
    async def test_process_movie_has_any_subs_false_when_no_present_subs(
        self, mock_db_session
    ):
        """Without any present subtitle file, has_any_subs is False."""

        class MockWantedMovie:
            title = "No Subs Movie"
            radarrId = 4243
            sceneName = "/bazarr/movies/No Subs Movie.mkv"
            missing_subtitles = []

        mock_movie = MockWantedMovie()
        path_map = PathMap()
        started_at = datetime.now(timezone.utc)

        await _process_movie(mock_db_session, mock_movie, path_map, started_at)

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "movie:4243")
        )
        entry = result.scalar_one_or_none()

        assert entry is not None
        assert entry.has_any_subs is False


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

    @pytest.mark.asyncio
    async def test_process_episode_has_any_subs_from_present_subtitles(
        self, mock_db_session
    ):
        """has_any_subs reflects PRESENT subtitle files, not the missing list (B10).

        Regression for B10: _process_episode used to derive has_any_subs from
        ``missing_subtitles == []`` (i.e. "fully satisfied"), which is the wrong
        signal for the frontend's "No subtitles only" filter. The authoritative
        source is the detail endpoint's ``subtitles`` list of files actually on
        disk.

        This pins that an episode which is still wanted for English but already
        HAS a French subtitle is reported as has_any_subs=True (so the "No
        subtitles only" filter correctly drops it).
        """

        class MockSubtitle:
            name = "French"
            code2 = "fr"
            code3 = "fre"
            forced = False
            hi = False

        class MockWantedEpisode:
            seriesTitle = "Test Show"
            episodeTitle = "Mixed"
            sonarrEpisodeId = 999
            sceneName = "/bazarr/tv/Test Show/Mixed.mkv"
            missing_subtitles = [MockSubtitle()]  # still missing English...

        mock_episode = MockWantedEpisode()
        path_map = PathMap([])
        started_at = datetime.now(timezone.utc)

        await _process_episode(
            mock_db_session,
            mock_episode,
            path_map,
            started_at,
            subtitles=[MockSubtitle()],  # ...but a French sub file is present
        )

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "episode:999")
        )
        entry = result.scalar_one_or_none()

        assert entry is not None
        assert entry.has_any_subs is True

    @pytest.mark.asyncio
    async def test_process_episode_has_any_subs_false_when_no_present_subs(
        self, mock_db_session
    ):
        """Without any present subtitle file, has_any_subs is False.

        The detail fetch is the only source of truth for present subs; when it
        yields nothing (or is unavailable), the item is conservatively reported
        as having no subs - even if the wanted endpoint reports nothing missing.
        """

        class MockWantedEpisode:
            seriesTitle = "Test Show"
            episodeTitle = "Complete"
            sonarrEpisodeId = 1000
            sceneName = "/bazarr/tv/Test Show/Complete.mkv"
            missing_subtitles = []

        mock_episode = MockWantedEpisode()
        path_map = PathMap([])
        started_at = datetime.now(timezone.utc)

        # No subtitles passed (None) -> conservatively reported as no subs.
        await _process_episode(mock_db_session, mock_episode, path_map, started_at)

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "episode:1000")
        )
        entry = result.scalar_one_or_none()

        assert entry is not None
        assert entry.has_any_subs is False

    @pytest.mark.asyncio
    async def test_process_episode_stores_audio_language(self, mock_db_session):
        """audio_language, when passed, is stored on the cache row."""

        class MockAudioLanguage:
            name = "German"
            code2 = "de"
            code3 = "ger"
            forced = False
            hi = False

        class MockWantedEpisode:
            seriesTitle = "German Show"
            episodeTitle = "Pilot"
            sonarrEpisodeId = 1001
            sonarrSeriesId = 2001
            sceneName = "/bazarr/tv/German Show/Pilot.mkv"
            missing_subtitles = []

        mock_episode = MockWantedEpisode()
        path_map = PathMap()
        started_at = datetime.now(timezone.utc)

        await _process_episode(
            mock_db_session,
            mock_episode,
            path_map,
            started_at,
            [MockAudioLanguage()],
        )

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "episode:1001")
        )
        entry = result.scalar_one_or_none()

        assert entry is not None
        assert entry.audio_language == [
            {
                "name": "German",
                "code2": "de",
                "code3": "ger",
                "forced": False,
                "hi": False,
            }
        ]


class TestProcessEpisodePath:
    """Test _process_episode media_path resolution from full-detail path."""

    @pytest.mark.asyncio
    async def test_process_episode_null_sceneName_uses_detail_path(
        self, mock_db_session
    ):
        """The wanted-episodes endpoint returns sceneName=None; the real file
        path is joined in from the full episodes endpoint and must populate
        media_path."""

        class MockWantedEpisode:
            seriesTitle = "Baron Noir"
            episodeTitle = "Jupiter"
            sonarrEpisodeId = 324
            sonarrSeriesId = 5
            sceneName = None
            missing_subtitles = []

        mock_episode = MockWantedEpisode()
        path_map = PathMap()
        started_at = datetime.now(timezone.utc)

        await _process_episode(
            mock_db_session,
            mock_episode,
            path_map,
            started_at,
            media_path_detail="/tv/Baron Noir/S01E03.mkv",
        )

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "episode:324")
        )
        entry = result.scalar_one()
        assert entry.media_path == "/tv/Baron Noir/S01E03.mkv"

    @pytest.mark.asyncio
    async def test_process_episode_prefers_detail_path_over_sceneName(
        self, mock_db_session
    ):
        """media_path_detail wins over sceneName when both are present."""

        class MockWantedEpisode:
            seriesTitle = "Test Show"
            episodeTitle = "Pilot"
            sonarrEpisodeId = 702
            sonarrSeriesId = 9
            sceneName = "Test.Show.S01E01.1080p.WEB.x264-GROUP"
            missing_subtitles = []

        mock_episode = MockWantedEpisode()
        path_map = PathMap([("/bazarr/tv", "/local/tv")])
        started_at = datetime.now(timezone.utc)

        await _process_episode(
            mock_db_session,
            mock_episode,
            path_map,
            started_at,
            media_path_detail="/bazarr/tv/Test Show/S01E01.mkv",
        )

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.id == "episode:702")
        )
        entry = result.scalar_one()
        assert entry.media_path == "/local/tv/Test Show/S01E01.mkv"


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

        # Capture the real wait_for before any patching to avoid self-recursion
        # when the patch replaces asyncio.wait_for on the shared asyncio module.
        real_wait_for = asyncio.wait_for

        @asynccontextmanager
        async def _tracked_session(_url: str):
            lifecycle.append("enter")
            yield Mock()
            lifecycle.append("exit")

        async def _tracked_wait_for(coro, timeout):
            lifecycle.append(f"wait:{int(timeout)}")
            # Trigger shutdown so the poller terminates after one iteration.
            mock_app.state.shutdown.set()
            await real_wait_for(coro, timeout=1.0)

        with (
            # get_async_session is imported locally inside run_bazarr_poller, so
            # patch at the source module (not the poller module attribute).
            patch("audio_to_subs.db.session.get_async_session", _tracked_session),
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
            await real_wait_for(run_bazarr_poller(mock_app), timeout=5.0)

        exit_idx = lifecycle.index("exit")
        wait_idx = next(i for i, e in enumerate(lifecycle) if e.startswith("wait:3600"))
        assert (
            exit_idx < wait_idx
        ), f"Session must close before the inter-poll sleep; lifecycle={lifecycle}"


class TestPollAllEpisodes:
    """Test _poll_all_episodes implementation."""

    @pytest.mark.asyncio
    async def test_poll_all_episodes_implementation(self, mock_db_session):
        """Test that _poll_all_episodes fetches and caches episodes with no subtitles."""
        from audio_to_subs.bazarr.client import BazarrClient
        from audio_to_subs.bazarr.pathmap import PathMap

        # Create mock client
        mock_client = AsyncMock(spec=BazarrClient)

        # Mock series and episodes responses
        from audio_to_subs.bazarr.schemas import (
            Episode,
            EpisodesPage,
            Series,
            SeriesPage,
        )

        mock_series = Series(
            sonarrSeriesId=1,
            title="Test Series",
            path="/tv/Test Series",
            tvdbId=123,
            imdbId=None,
            monitored=True,
            profileId=None,
            seriesType="standard",
            tags=[],
            alternativeTitles=[],
            ended=False,
            lastAired=None,
            fanart=None,
            poster=None,
            overview=None,
            year=None,
            audio_language=None,
        )

        mock_episode_no_subs = Episode(
            sonarrEpisodeId=100,
            sonarrSeriesId=789,
            title="Test Episode",
            subtitles=[],  # No subtitles
            season=1,
            episode=1,
            path="/bazarr/tv/Test Series/Season 01/Episode 01.mkv",
            sceneName="/bazarr/tv/Test Series/Season 01/Episode 01.mkv",
        )

        mock_episode_with_subs = Episode(
            sonarrEpisodeId=101,
            sonarrSeriesId=789,
            title="Test Episode 2",
            subtitles=[
                {
                    "code2": "en",
                    "code3": "eng",
                    "name": "English",
                    "forced": False,
                    "hi": False,
                }
            ],  # Has subtitles
            season=1,
            episode=2,
            path="/bazarr/tv/Test Series/Season 01/Episode 02.mkv",
            sceneName="/bazarr/tv/Test Series/Season 01/Episode 02.mkv",
        )

        mock_client.list_all_series.return_value = SeriesPage(
            data=[mock_series],
            total=1,
        )
        mock_client.list_episodes.return_value = EpisodesPage(
            data=[mock_episode_no_subs, mock_episode_with_subs],
        )

        path_map = PathMap([("/bazarr/tv", "/local/tv")])
        started_at = datetime.now(timezone.utc)

        # Call the function
        await _poll_all_episodes(mock_db_session, mock_client, path_map, started_at)

        # Verify only episode without subtitles was cached
        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.kind == "episode")
        )
        cached = result.scalars().all()

        assert len(cached) == 1
        assert cached[0].ext_id == 100  # Only the episode without subs
        assert cached[0].has_any_subs is False
        assert "/local/tv" in cached[0].media_path  # Path was translated


class TestPollAllEpisodesRealisticWireFormat:
    """`bazarr_track_no_subs` polling against Bazarr's real /api/series wire format.

    Unlike TestPollAllEpisodes above (which mocks list_all_series at the
    client-method level, bypassing schema validation entirely), this drives
    a REAL BazarrClient through respx so the actual /api/series response
    Bazarr sends is parsed - proving the opt-in "track items with no
    subtitles" feature survives it instead of silently logging a warning
    and skipping every series (the schema bug this test guards against).
    """

    @pytest.mark.asyncio
    async def test_poll_all_episodes_survives_realistic_series_payload(
        self, mock_db_session, respx_mock
    ):
        import httpx

        from tests.bazarr_fixtures import realistic_series_item

        respx_mock.get("http://poller-wire-test:6767/api/series").mock(
            return_value=httpx.Response(
                200,
                json={"data": [realistic_series_item(sonarrSeriesId=789)], "total": 1},
            )
        )
        respx_mock.get("http://poller-wire-test:6767/api/episodes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "sonarrEpisodeId": 100,
                            "sonarrSeriesId": 789,
                            "title": "Test Episode",
                            "subtitles": [],
                            "season": 1,
                            "episode": 1,
                            "path": "/bazarr/tv/Test Series/Season 01/Episode 01.mkv",
                            "sceneName": "/bazarr/tv/Test Series/Season 01/Episode 01.mkv",
                        }
                    ],
                    "total": 1,
                },
            )
        )

        path_map = PathMap([("/bazarr/tv", "/local/tv")])
        started_at = datetime.now(timezone.utc)

        async with BazarrClient(
            base_url="http://poller-wire-test:6767",
            api_key="wire-test-key",
        ) as client:
            await _poll_all_episodes(mock_db_session, client, path_map, started_at)

        result = await mock_db_session.execute(
            select(BazarrCache).where(BazarrCache.kind == "episode")
        )
        cached = result.scalars().all()

        assert len(cached) == 1
        assert cached[0].ext_id == 100
        assert cached[0].has_any_subs is False


class TestManualPolling:
    """Test manual polling functionality with type filtering."""

    @pytest.mark.asyncio
    async def test_manual_poll_all(self, mock_db_session):
        """Test manual polling without type filter polls both movies and episodes."""
        from audio_to_subs.bazarr.poller import poll_bazarr_manually
        from audio_to_subs.bazarr.schemas import (
            WantedEpisode,
            WantedEpisodesPage,
            WantedMovie,
            WantedMoviesPage,
        )

        # Create mock client
        mock_client = AsyncMock(spec=BazarrClient)

        movie = WantedMovie(
            title="Test Movie",
            radarrId=123,
            sceneName="/bazarr/movies/Test Movie.mkv",
        )
        episode = WantedEpisode(
            seriesTitle="Test Series",
            episode_number="S01E01",
            episodeTitle="Pilot",
            sonarrSeriesId=1,
            sonarrEpisodeId=456,
        )

        mock_client.list_wanted_movies.return_value = WantedMoviesPage(
            data=[movie], total=1
        )
        mock_client.list_wanted_episodes.return_value = WantedEpisodesPage(
            data=[episode], total=1
        )

        path_map = PathMap()

        # Call the function
        movies_processed, episodes_processed = await poll_bazarr_manually(
            mock_db_session, mock_client, path_map, None
        )

        # Verify both API calls were made
        mock_client.list_wanted_movies.assert_awaited_once()
        mock_client.list_wanted_episodes.assert_awaited_once()

        # Verify counts
        assert movies_processed == 1
        assert episodes_processed == 1

        await mock_client.close()

    @pytest.mark.asyncio
    async def test_manual_poll_movies_only(self, mock_db_session):
        """Test manual polling for movies only skips episode API calls."""
        from audio_to_subs.api.routes.wanted import WantedItemType
        from audio_to_subs.bazarr.poller import poll_bazarr_manually
        from audio_to_subs.bazarr.schemas import (
            WantedEpisodesPage,
            WantedMovie,
            WantedMoviesPage,
        )

        # Create mock client
        mock_client = AsyncMock(spec=BazarrClient)

        movie = WantedMovie(
            title="Test Movie",
            radarrId=123,
            sceneName="/bazarr/movies/Test Movie.mkv",
        )

        mock_client.list_wanted_movies.return_value = WantedMoviesPage(
            data=[movie], total=1
        )
        mock_client.list_wanted_episodes.return_value = WantedEpisodesPage(
            data=[], total=0
        )

        path_map = PathMap()

        # Call the function with movies only filter
        movies_processed, episodes_processed = await poll_bazarr_manually(
            mock_db_session, mock_client, path_map, WantedItemType.MOVIE
        )

        # Verify only movie API call was made
        mock_client.list_wanted_movies.assert_awaited_once()
        # Episode API should not be called
        mock_client.list_wanted_episodes.assert_not_awaited()

        # Verify counts
        assert movies_processed == 1
        assert episodes_processed == 0

        await mock_client.close()

    @pytest.mark.asyncio
    async def test_manual_poll_episodes_only(self, mock_db_session):
        """Test manual polling for episodes only skips movie API calls."""
        from audio_to_subs.api.routes.wanted import WantedItemType
        from audio_to_subs.bazarr.poller import poll_bazarr_manually
        from audio_to_subs.bazarr.schemas import (
            WantedEpisode,
            WantedEpisodesPage,
            WantedMoviesPage,
        )

        # Create mock client
        mock_client = AsyncMock(spec=BazarrClient)

        episode = WantedEpisode(
            seriesTitle="Test Series",
            episode_number="S01E01",
            episodeTitle="Pilot",
            sonarrSeriesId=1,
            sonarrEpisodeId=456,
        )

        mock_client.list_wanted_movies.return_value = WantedMoviesPage(data=[], total=0)
        mock_client.list_wanted_episodes.return_value = WantedEpisodesPage(
            data=[episode], total=1
        )

        path_map = PathMap()

        # Call the function with episodes only filter
        movies_processed, episodes_processed = await poll_bazarr_manually(
            mock_db_session, mock_client, path_map, WantedItemType.EPISODE
        )

        # Verify only episode API call was made
        mock_client.list_wanted_episodes.assert_awaited_once()
        # Movie API should not be called
        mock_client.list_wanted_movies.assert_not_awaited()

        # Verify counts
        assert movies_processed == 0
        assert episodes_processed == 1

        await mock_client.close()

    @pytest.mark.asyncio
    async def test_manual_poll_with_track_no_subs(self, mock_db_session):
        """Test manual polling respects bazarr_track_no_subs setting."""
        import json

        from audio_to_subs.api.routes.wanted import WantedItemType
        from audio_to_subs.bazarr.poller import poll_bazarr_manually
        from audio_to_subs.bazarr.schemas import (
            Episode,
            EpisodesPage,
            Movie,
            MoviesPage,
            Series,
            SeriesPage,
            WantedEpisode,
            WantedEpisodesPage,
            WantedMovie,
            WantedMoviesPage,
        )
        from audio_to_subs.db.models import Setting

        # Enable track_no_subs setting
        setting = Setting(
            key="bazarr_track_no_subs",
            value_json=json.dumps(True),
        )
        mock_db_session.add(setting)
        await mock_db_session.commit()

        # Create mock client
        mock_client = AsyncMock(spec=BazarrClient)

        movie = WantedMovie(
            title="Test Movie",
            radarrId=123,
            sceneName="/bazarr/movies/Test Movie.mkv",
        )
        episode = WantedEpisode(
            seriesTitle="Test Series",
            episode_number="S01E01",
            episodeTitle="Pilot",
            sonarrSeriesId=1,
            sonarrEpisodeId=456,
        )

        # Movie with no subtitles
        movie_no_subs = Movie(
            radarrId=789,
            title="Movie No Subs",
            sceneName="/bazarr/movies/No Subs.mkv",
            subtitles=[],
        )

        # Series and episode with no subtitles
        series_no_subs = Series(
            sonarrSeriesId=101,
            title="Series No Subs",
            path="/bazarr/tv/Series No Subs",
            monitored=True,
            ended=False,
        )
        episode_no_subs = Episode(
            sonarrEpisodeId=202,
            sonarrSeriesId=101,
            title="Episode No Subs",
            path="/bazarr/tv/Series No Subs/ep1.mkv",
            sceneName="/bazarr/tv/Series No Subs/ep1.mkv",
            subtitles=[],
        )

        mock_client.list_wanted_movies.return_value = WantedMoviesPage(
            data=[movie], total=1
        )
        mock_client.list_wanted_episodes.return_value = WantedEpisodesPage(
            data=[episode], total=1
        )
        mock_client.list_all_movies.return_value = MoviesPage(
            data=[movie_no_subs], total=1
        )
        mock_client.list_all_series.return_value = SeriesPage(
            data=[series_no_subs], total=1
        )
        mock_client.list_episodes.return_value = EpisodesPage(data=[episode_no_subs])

        path_map = PathMap()

        # Call the function with ALL type (which should also poll all items when track_no_subs is enabled)
        movies_processed, episodes_processed = await poll_bazarr_manually(
            mock_db_session, mock_client, path_map, WantedItemType.ALL
        )

        # Verify all API calls were made (wanted + all for track_no_subs).
        # list_all_movies/list_episodes are each called twice here: once to
        # batch-fetch audio_language for the wanted items, and once more by
        # the (independent) track_no_subs full-library scan - two distinct
        # purposes, not a regression of the "bounded, not per-item" guarantee.
        mock_client.list_wanted_movies.assert_awaited_once()
        mock_client.list_wanted_episodes.assert_awaited_once()
        assert mock_client.list_all_movies.await_count == 2
        mock_client.list_all_series.assert_awaited_once()
        assert mock_client.list_episodes.await_count == 2

        # Verify counts include both wanted and no-subs items
        assert movies_processed >= 1  # At least the wanted movie
        assert episodes_processed >= 1  # At least the wanted episode

        await mock_client.close()

    @pytest.mark.asyncio
    async def test_manual_poll_handles_client_error(
        self, mock_db_session, sync_session
    ):
        """Test manual polling propagates Bazarr client errors instead of masking them as success."""
        from sqlalchemy import select

        from audio_to_subs.bazarr.client import BazarrServerError
        from audio_to_subs.bazarr.poller import poll_bazarr_manually
        from audio_to_subs.db.models import JobLog, LogLevel

        # Create mock client that raises error
        mock_client = AsyncMock(spec=BazarrClient)
        mock_client.list_wanted_movies.side_effect = BazarrServerError("Server error")

        path_map = PathMap()

        # A failure fetching wanted movies must propagate, not be swallowed and
        # reported as a successful poll with 0 items processed.
        with pytest.raises(BazarrServerError):
            await poll_bazarr_manually(mock_db_session, mock_client, path_map, None)

        await mock_client.close()

        # The failure must also be visible in the UI's activity log, not just
        # propagated as an exception.
        log = sync_session.execute(select(JobLog)).scalar_one()
        assert log.job_id is None
        assert log.level == LogLevel.ERROR
        assert "Bazarr sync failed" in log.message

    @pytest.mark.asyncio
    async def test_manual_poll_returns_counts(self, mock_db_session, sync_session):
        """Test manual polling returns accurate counts."""
        from sqlalchemy import select

        from audio_to_subs.bazarr.poller import poll_bazarr_manually
        from audio_to_subs.bazarr.schemas import (
            WantedEpisode,
            WantedEpisodesPage,
            WantedMovie,
            WantedMoviesPage,
        )
        from audio_to_subs.db.models import JobLog, LogLevel

        # Create mock client
        mock_client = AsyncMock(spec=BazarrClient)

        movies = [
            WantedMovie(title=f"Movie {i}", radarrId=i, sceneName=f"/m{i}.mkv")
            for i in range(1, 4)
        ]
        episodes = [
            WantedEpisode(
                seriesTitle="Series 1",
                episode_number=f"S01E0{i}",
                episodeTitle=f"Ep{i}",
                sonarrSeriesId=1,
                sonarrEpisodeId=100 + i,
            )
            for i in range(1, 3)
        ]

        mock_client.list_wanted_movies.return_value = WantedMoviesPage(
            data=movies, total=3
        )
        mock_client.list_wanted_episodes.return_value = WantedEpisodesPage(
            data=episodes, total=2
        )

        path_map = PathMap()

        # Call the function
        movies_processed, episodes_processed = await poll_bazarr_manually(
            mock_db_session, mock_client, path_map, None
        )

        # Verify counts are accurate
        assert movies_processed == 3
        assert episodes_processed == 2

        # A successful sync must also be visible in the UI's activity log,
        # with the counts in the message.
        log = sync_session.execute(select(JobLog)).scalar_one()
        assert log.job_id is None
        assert log.level == LogLevel.INFO
        assert "3 movies" in log.message
        assert "2 episodes" in log.message


class TestAudioLanguageEnrichment:
    """Test that poll_bazarr_manually joins in audio_language from the
    full-detail endpoints, bounded (one call per poll / per distinct series),
    not one call per wanted item."""

    @pytest.mark.asyncio
    async def test_movies_audio_language_batched_and_joined(self, mock_db_session):
        from audio_to_subs.bazarr.poller import poll_bazarr_manually
        from audio_to_subs.bazarr.schemas import (
            Movie,
            MoviesPage,
            SubtitleLanguage,
            WantedMovie,
            WantedMoviesPage,
        )

        mock_client = AsyncMock(spec=BazarrClient)
        mock_client.list_wanted_movies.return_value = WantedMoviesPage(
            data=[
                WantedMovie(title="Movie A", radarrId=1, sceneName="/a.mkv"),
                WantedMovie(title="Movie B", radarrId=2, sceneName="/b.mkv"),
            ],
            total=2,
        )
        mock_client.list_wanted_episodes.return_value.data = []
        mock_client.list_all_movies.return_value = MoviesPage(
            data=[
                Movie(
                    title="Movie A",
                    radarrId=1,
                    audio_language=[
                        SubtitleLanguage(name="French", code2="fr", code3="fre")
                    ],
                ),
                Movie(
                    title="Movie B",
                    radarrId=2,
                    audio_language=[
                        SubtitleLanguage(name="German", code2="de", code3="ger")
                    ],
                ),
            ],
            total=2,
        )

        path_map = PathMap()
        await poll_bazarr_manually(mock_db_session, mock_client, path_map, "movie")

        # Bounded: exactly one call for this poll, not one per movie.
        mock_client.list_all_movies.assert_awaited_once_with(radarrid=[1, 2])

        entry_a = (
            await mock_db_session.execute(
                select(BazarrCache).where(BazarrCache.id == "movie:1")
            )
        ).scalar_one()
        entry_b = (
            await mock_db_session.execute(
                select(BazarrCache).where(BazarrCache.id == "movie:2")
            )
        ).scalar_one()
        assert entry_a.audio_language[0]["code2"] == "fr"
        assert entry_b.audio_language[0]["code2"] == "de"

    @pytest.mark.asyncio
    async def test_episodes_audio_language_batched_by_unique_series(
        self, mock_db_session
    ):
        from audio_to_subs.bazarr.poller import poll_bazarr_manually
        from audio_to_subs.bazarr.schemas import (
            Episode,
            EpisodesPage,
            SubtitleLanguage,
            WantedEpisode,
            WantedEpisodesPage,
        )

        mock_client = AsyncMock(spec=BazarrClient)
        mock_client.list_wanted_movies.return_value.data = []
        # Three wanted episodes across only two distinct series.
        mock_client.list_wanted_episodes.return_value = WantedEpisodesPage(
            data=[
                WantedEpisode(
                    seriesTitle="Series 1",
                    episode_number="S01E01",
                    episodeTitle="Ep1",
                    sonarrSeriesId=10,
                    sonarrEpisodeId=101,
                ),
                WantedEpisode(
                    seriesTitle="Series 1",
                    episode_number="S01E02",
                    episodeTitle="Ep2",
                    sonarrSeriesId=10,
                    sonarrEpisodeId=102,
                ),
                WantedEpisode(
                    seriesTitle="Series 2",
                    episode_number="S01E01",
                    episodeTitle="Ep1",
                    sonarrSeriesId=20,
                    sonarrEpisodeId=201,
                ),
            ],
            total=3,
        )

        def list_episodes_side_effect(*, seriesid):
            if seriesid == 10:
                return EpisodesPage(
                    data=[
                        Episode(
                            sonarrEpisodeId=101,
                            sonarrSeriesId=10,
                            title="Ep1",
                            audio_language=[
                                SubtitleLanguage(name="English", code2="en")
                            ],
                        ),
                        Episode(
                            sonarrEpisodeId=102,
                            sonarrSeriesId=10,
                            title="Ep2",
                            audio_language=[
                                SubtitleLanguage(name="English", code2="en")
                            ],
                        ),
                    ]
                )
            return EpisodesPage(
                data=[
                    Episode(
                        sonarrEpisodeId=201,
                        sonarrSeriesId=20,
                        title="Ep1",
                        audio_language=[SubtitleLanguage(name="Spanish", code2="es")],
                    ),
                ]
            )

        mock_client.list_episodes.side_effect = list_episodes_side_effect

        path_map = PathMap()
        await poll_bazarr_manually(mock_db_session, mock_client, path_map, "episode")

        # Bounded by distinct series (2), not by wanted-episode count (3).
        assert mock_client.list_episodes.await_count == 2

        entry_101 = (
            await mock_db_session.execute(
                select(BazarrCache).where(BazarrCache.id == "episode:101")
            )
        ).scalar_one()
        entry_201 = (
            await mock_db_session.execute(
                select(BazarrCache).where(BazarrCache.id == "episode:201")
            )
        ).scalar_one()
        assert entry_101.audio_language[0]["code2"] == "en"
        assert entry_201.audio_language[0]["code2"] == "es"

    @pytest.mark.asyncio
    async def test_audio_language_fetch_failure_degrades_gracefully(
        self, mock_db_session
    ):
        """If the enrichment call fails, the poll must still succeed - items
        just end up with an empty audio_language (Auto-only in the UI)."""
        from audio_to_subs.bazarr.poller import poll_bazarr_manually
        from audio_to_subs.bazarr.schemas import WantedMovie, WantedMoviesPage

        mock_client = AsyncMock(spec=BazarrClient)
        mock_client.list_wanted_movies.return_value = WantedMoviesPage(
            data=[WantedMovie(title="Movie A", radarrId=1, sceneName="/a.mkv")],
            total=1,
        )
        mock_client.list_wanted_episodes.return_value.data = []
        mock_client.list_all_movies.side_effect = Exception("Bazarr unreachable")

        path_map = PathMap()
        movies_processed, _ = await poll_bazarr_manually(
            mock_db_session, mock_client, path_map, "movie"
        )

        assert movies_processed == 1
        entry = (
            await mock_db_session.execute(
                select(BazarrCache).where(BazarrCache.id == "movie:1")
            )
        ).scalar_one()
        assert entry.audio_language == []

        await mock_client.close()
