"""Tests for Bazarr API client."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from audio_to_subs.bazarr.client import (
    BazarrAuthError,
    BazarrClient,
    BazarrError,
    BazarrNotFoundError,
    BazarrRateLimited,
    BazarrServerError,
)
from audio_to_subs.bazarr.schemas import SubtitleLanguage
from tests.bazarr_fixtures import (
    null_heavy_series_item,
    realistic_movie_item,
    realistic_series_item,
)


@pytest.fixture
def mock_client():
    """Create a mock BazarrClient for testing."""
    return BazarrClient(
        base_url="http://test-bazarr:6767",
        api_key="test-api-key",
    )


class TestBazarrClientInit:
    """Test BazarrClient initialization."""

    def test_init_basic(self):
        """Test basic initialization."""
        client = BazarrClient(
            base_url="http://localhost:6767",
            api_key="test-key",
        )

        assert client.base_url == "http://localhost:6767"
        assert client.api_key == "test-key"

    def test_init_with_trailing_slash(self):
        """Test initialization with trailing slash in base_url."""
        client = BazarrClient(
            base_url="http://localhost:6767/",
            api_key="test-key",
        )

        assert client.base_url == "http://localhost:6767"

    def test_init_with_custom_timeouts(self):
        """Test initialization with custom timeouts."""
        client = BazarrClient(
            base_url="http://localhost:6767",
            api_key="test-key",
            connect_timeout=5.0,
            read_timeout=60.0,
        )

        # The timeout object should be created with custom values
        assert client.timeout.connect == 5.0
        assert client.timeout.read == 60.0


class TestBazarrClientContextManager:
    """Test async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_client):
        """Test that client can be used as async context manager."""
        async with mock_client as client:
            assert client is mock_client

        # Client should be closed after context exit
        assert mock_client._client is None

    @pytest.mark.asyncio
    async def test_close(self, mock_client):
        """Test explicit close."""
        await mock_client._ensure_client()
        assert mock_client._client is not None

        await mock_client.close()
        assert mock_client._client is None


class TestBazarrClientHeaders:
    """Test that client sends correct headers."""

    @pytest.mark.asyncio
    async def test_api_key_header(self, mock_client):
        """Test that X-API-Key header is sent."""
        await mock_client._ensure_client()

        # The headers should include the API key
        assert "X-API-Key" in mock_client._headers
        assert mock_client._headers["X-API-Key"] == "test-api-key"


class TestBazarrExceptions:
    """Test custom exceptions."""

    def test_exception_hierarchy(self):
        """Test exception hierarchy."""
        assert issubclass(BazarrAuthError, BazarrError)
        assert issubclass(BazarrNotFoundError, BazarrError)
        assert issubclass(BazarrRateLimited, BazarrError)
        assert issubclass(BazarrServerError, BazarrError)

    def test_rate_limited_with_retry_after(self):
        """Test BazarrRateLimited with retry_after."""
        error = BazarrRateLimited(retry_after=30)
        assert error.retry_after == 30
        assert "30 seconds" in str(error)

    def test_rate_limited_without_retry_after(self):
        """Test BazarrRateLimited without retry_after."""
        error = BazarrRateLimited(retry_after=None)
        assert error.retry_after is None
        assert "None" in str(error)


# Tests with respx for mocking HTTP requests
class TestBazarrClientRequests:
    """Test client HTTP requests with respx.

    Generic error/retry handling (auth, not-found, rate-limit, 5xx/backoff)
    is exercised against `/api/movies` (list_all_movies) - the full-sync
    poller's real entry point - rather than the retired wanted endpoints;
    the retry/backoff machinery itself is endpoint-agnostic, so any GET
    endpoint proves the same behavior.
    """

    @pytest.mark.asyncio
    async def test_auth_error(self, respx_mock):
        """Test 401 authentication error."""
        respx_mock.get("http://test-bazarr:6767/api/movies").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"}),
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="wrong-key",
        ) as client:
            with pytest.raises(BazarrAuthError):
                await client.list_all_movies()

    @pytest.mark.asyncio
    async def test_not_found_error(self, respx_mock):
        """Test 404 not found error."""
        respx_mock.get("http://test-bazarr:6767/api/nonexistent").mock(
            return_value=httpx.Response(404, json={"error": "Not found"}),
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            with pytest.raises(BazarrNotFoundError):
                await client._get("/api/nonexistent")

    @pytest.mark.asyncio
    async def test_rate_limited_error(self, respx_mock):
        """Test 429 rate limited error raises after retries are exhausted."""
        route = respx_mock.get("http://test-bazarr:6767/api/movies").mock(
            return_value=httpx.Response(
                429, json={"error": "Rate limited"}, headers={"Retry-After": "30"}
            ),
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            with patch(
                "audio_to_subs.bazarr.client.asyncio.sleep", new=AsyncMock()
            ) as mock_sleep:
                with pytest.raises(BazarrRateLimited) as exc_info:
                    await client.list_all_movies()

                assert exc_info.value.retry_after == 30
                # Retries exhausted: 1 initial attempt + max_retries retries.
                assert route.call_count == client.max_retries + 1
                # Retry-After was honored for every backoff wait.
                assert mock_sleep.await_count == client.max_retries
                for call in mock_sleep.await_args_list:
                    assert call.args[0] == 30

    @pytest.mark.asyncio
    async def test_rate_limited_then_success(self, respx_mock):
        """Test that a 429 followed by a 200 succeeds via retry."""
        route = respx_mock.get("http://test-bazarr:6767/api/movies")
        route.side_effect = [
            httpx.Response(
                429, json={"error": "Rate limited"}, headers={"Retry-After": "5"}
            ),
            httpx.Response(200, json={"data": [], "total": 0}),
        ]

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            with patch(
                "audio_to_subs.bazarr.client.asyncio.sleep", new=AsyncMock()
            ) as mock_sleep:
                result = await client.list_all_movies()

                assert result.total == 0
                assert route.call_count == 2
                mock_sleep.assert_awaited_once_with(5)

    @pytest.mark.asyncio
    async def test_server_error_with_retry(self, respx_mock):
        """Test 5xx server error with retry."""
        # First request fails with 500, second succeeds — use httpx.Response explicitly.
        respx_mock.get("http://test-bazarr:6767/api/movies").side_effect = [
            httpx.Response(500, json={"error": "Server error"}),
            httpx.Response(200, json={"data": [], "total": 0}),
        ]

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            with patch("audio_to_subs.bazarr.client.asyncio.sleep", new=AsyncMock()):
                result = await client.list_all_movies()
                assert result.total == 0

    @pytest.mark.asyncio
    async def test_server_error_exponential_backoff(self, respx_mock):
        """Test that repeated 5xx errors (no Retry-After) back off exponentially."""
        route = respx_mock.get("http://test-bazarr:6767/api/movies")
        route.side_effect = [
            httpx.Response(503, json={"error": "Server error"}),
            httpx.Response(503, json={"error": "Server error"}),
            httpx.Response(200, json={"data": [], "total": 0}),
        ]

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
            backoff_base=1.0,
            backoff_max=30.0,
        ) as client:
            with patch(
                "audio_to_subs.bazarr.client.asyncio.sleep", new=AsyncMock()
            ) as mock_sleep:
                result = await client.list_all_movies()

                assert result.total == 0
                assert route.call_count == 3
                # Exponential backoff: 1s then 2s (backoff_base * 2**attempt).
                assert [call.args[0] for call in mock_sleep.await_args_list] == [
                    1.0,
                    2.0,
                ]

    @pytest.mark.asyncio
    async def test_server_error_exhausts_retries(self, respx_mock):
        """Test that persistent 5xx errors raise BazarrServerError once retries are exhausted."""
        route = respx_mock.get("http://test-bazarr:6767/api/movies").mock(
            return_value=httpx.Response(500, json={"error": "Server error"}),
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
            max_retries=2,
        ) as client:
            with patch("audio_to_subs.bazarr.client.asyncio.sleep", new=AsyncMock()):
                with pytest.raises(BazarrServerError):
                    await client.list_all_movies()

                assert route.call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_backoff_capped_at_backoff_max(self, respx_mock):
        """Test that a large Retry-After value is capped at backoff_max."""
        route = respx_mock.get("http://test-bazarr:6767/api/movies")
        route.side_effect = [
            httpx.Response(
                429,
                json={"error": "Rate limited"},
                headers={"Retry-After": "9999"},
            ),
            httpx.Response(200, json={"data": [], "total": 0}),
        ]

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
            backoff_max=15.0,
        ) as client:
            with patch(
                "audio_to_subs.bazarr.client.asyncio.sleep", new=AsyncMock()
            ) as mock_sleep:
                result = await client.list_all_movies()

                assert result.total == 0
                mock_sleep.assert_awaited_once_with(15.0)


class TestRescan:
    """Test rescan methods using PATCH endpoints."""

    @pytest.mark.asyncio
    async def test_rescan_movie_uses_patch(self, respx_mock):
        """Test that rescan_movie uses PATCH /api/movies with action=scan-disk."""
        route = respx_mock.patch("http://test-bazarr:6767/api/movies")
        route.mock(return_value=httpx.Response(202))

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.rescan_movie(123)
            assert result is True
            # Verify the request was made with correct params
            assert len(route.calls) == 1
            assert route.calls[0].request.url.params.get("radarrid") == "123"
            assert route.calls[0].request.url.params.get("action") == "scan-disk"

    @pytest.mark.asyncio
    async def test_rescan_episode_uses_patch(self, respx_mock):
        """Test that rescan_episode uses PATCH /api/series with action=scan-disk."""
        route = respx_mock.patch("http://test-bazarr:6767/api/series")
        route.mock(return_value=httpx.Response(202))

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.rescan_episode(456, series_id=789)
            assert result is True
            # Verify the request was made with correct params
            assert len(route.calls) == 1
            assert route.calls[0].request.url.params.get("seriesid") == "789"
            assert route.calls[0].request.url.params.get("action") == "scan-disk"

    @pytest.mark.asyncio
    async def test_rescan_episode_requires_series_id(self, respx_mock):
        """Test that rescan_episode requires series_id and returns False without it."""
        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            # Call without series_id should return False
            result = await client.rescan_episode(456)
            assert result is False

    @pytest.mark.asyncio
    async def test_rescan_movie_single_call(self, respx_mock):
        """Test that rescan_movie makes only one call (no outer retry loop)."""
        route = respx_mock.patch("http://test-bazarr:6767/api/movies")
        route.mock(return_value=httpx.Response(202))

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.rescan_movie(123)
            assert result is True
            # Verify only one call was made (no outer retry loop)
            assert len(route.calls) == 1

    @pytest.mark.asyncio
    async def test_rescan_episode_single_call(self, respx_mock):
        """Test that rescan_episode makes only one call (no outer retry loop)."""
        route = respx_mock.patch("http://test-bazarr:6767/api/series")
        route.mock(return_value=httpx.Response(202))

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.rescan_episode(456, series_id=789)
            assert result is True
            # Verify only one call was made (no outer retry loop)
            assert len(route.calls) == 1


class TestMovies:
    """Test /api/movies endpoint (list_all_movies) - the Movie schema's
    audio_language field is a previously-unmodeled bug fix: Bazarr always
    sent it, but pydantic v2 silently dropped it since the field wasn't
    declared.
    """

    @pytest.mark.asyncio
    async def test_list_all_movies_audio_language_round_trips(self, respx_mock):
        """Movie.audio_language must be parsed, not silently dropped."""
        mock_response = {"data": [realistic_movie_item()], "total": 1}
        respx_mock.get("http://test-bazarr:6767/api/movies").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_all_movies()
            assert len(result.data) == 1
            assert result.data[0].radarrId == 1
            assert result.data[0].audio_language == [
                SubtitleLanguage(name="French", code2="fr", code3="fre")
            ]

    @pytest.mark.asyncio
    async def test_list_all_movies_audio_language_null_column(self, respx_mock):
        """A NULL audio_language column marshals as a dict of nulls.

        Same quirk as Series/Episode - must normalize to an empty list.
        """
        mock_response = {
            "data": [
                realistic_movie_item(
                    audio_language={"name": None, "code2": None, "code3": None}
                )
            ],
            "total": 1,
        }
        respx_mock.get("http://test-bazarr:6767/api/movies").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_all_movies()
            assert result.data[0].audio_language == []

    @pytest.mark.asyncio
    async def test_list_all_movies_audio_language_unknown_track(self, respx_mock):
        """An unresolved audio track has null code2/code3 but a real entry."""
        mock_response = {
            "data": [
                realistic_movie_item(
                    audio_language=[{"name": "Unknown", "code2": None, "code3": None}]
                )
            ],
            "total": 1,
        }
        respx_mock.get("http://test-bazarr:6767/api/movies").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_all_movies()
            assert result.data[0].audio_language[0].name == "Unknown"
            assert result.data[0].audio_language[0].code2 is None


class TestSeries:
    """Test series endpoint."""

    @pytest.mark.asyncio
    async def test_list_all_series(self, respx_mock):
        """Test list_all_series returns SeriesPage from a realistic payload.

        Bazarr marshals `audio_language` as a JSON array (never the bare dict
        our schema previously expected) - this fixture is the actual wire
        shape, reverse-engineered from Bazarr's source, not our own guess.
        """
        mock_response = {"data": [realistic_series_item()], "total": 1}
        respx_mock.get("http://test-bazarr:6767/api/series").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_all_series()
            assert len(result.data) == 1
            assert result.total == 1
            assert result.data[0].sonarrSeriesId == 123
            assert result.data[0].title == "Test Series"
            assert result.data[0].audio_language == [
                SubtitleLanguage(name="English", code2="en", code3="eng")
            ]

    @pytest.mark.asyncio
    async def test_list_all_series_null_heavy_item(self, respx_mock):
        """Only path/title/sonarrSeriesId are non-nullable in Bazarr's DB.

        A freshly-added series can have every other field null - the schema
        must tolerate that instead of requiring values Bazarr never promises.
        """
        mock_response = {"data": [null_heavy_series_item()], "total": 1}
        respx_mock.get("http://test-bazarr:6767/api/series").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_all_series()
            series = result.data[0]
            assert series.path == "/tv/Minimal Series"
            assert series.monitored is False
            assert series.ended is False
            assert series.audio_language == []

    @pytest.mark.asyncio
    async def test_list_all_series_audio_language_null_column(self, respx_mock):
        """A NULL audio_language column marshals as a dict of nulls.

        flask-restx's `fields.Nested` over a `None` value emits a dict with
        every key null - not the populated dict our old schema expected, and
        not the array shape either. Must normalize to an empty list.
        """
        mock_response = {
            "data": [
                realistic_series_item(
                    audio_language={"name": None, "code2": None, "code3": None}
                )
            ],
            "total": 1,
        }
        respx_mock.get("http://test-bazarr:6767/api/series").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_all_series()
            assert result.data[0].audio_language == []

    @pytest.mark.asyncio
    async def test_list_all_series_empty_library(self, respx_mock):
        """An empty Bazarr library returns {"data": [], "total": 0}."""
        respx_mock.get("http://test-bazarr:6767/api/series").mock(
            return_value=httpx.Response(200, json={"data": [], "total": 0})
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_all_series()
            assert result.data == []
            assert result.total == 0

    @pytest.mark.asyncio
    async def test_list_all_series_paged_total_is_unfiltered_count(self, respx_mock):
        """`total` is the whole library's count, not len(data), when paged.

        A length=1 probe against a large library returns total >> len(data);
        callers must not assume total reflects the page size.
        """
        mock_response = {"data": [realistic_series_item()], "total": 458}
        route = respx_mock.get("http://test-bazarr:6767/api/series").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_all_series(start=0, length=1)
            assert len(result.data) == 1
            assert result.total == 458
            assert len(respx_mock.calls) == 1
            query_string = str(route.calls[0].request.url.query)
            assert "length=1" in query_string

    @pytest.mark.asyncio
    async def test_list_episodes(self, respx_mock):
        """Test list_episodes uses seriesid[] parameter.

        Bazarr's /api/episodes marshals with envelope='data' only - no
        top-level `total` (unlike /api/series and the /wanted endpoints),
        so the mock omits it.
        """
        mock_response = {
            "data": [
                {
                    "sonarrEpisodeId": 100,
                    "sonarrSeriesId": 123,
                    "title": "Test Episode",
                    "subtitles": [],
                    "season": 1,
                    "episode": 1,
                    "path": "/tv/Test Series/Season 01/Episode 01.mkv",
                    "sceneName": "/tv/Test Series/Season 01/Episode 01.mkv",
                }
            ],
        }

        respx_mock.get("http://test-bazarr:6767/api/episodes").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_episodes(seriesid=123)

            assert len(result.data) == 1
            assert result.data[0].sonarrEpisodeId == 100
            assert result.data[0].sonarrSeriesId == 123
            # Verify the request was made with correct parameter name
            assert len(respx_mock.calls) == 1
            query_string = str(respx_mock.calls[0].request.url.query)
            # seriesid[] is URL-encoded as seriesid%5B%5D
            assert "seriesid%5B%5D" in query_string or "seriesid[]" in query_string

    @pytest.mark.asyncio
    async def test_list_episodes_accepts_batched_series_ids(self, respx_mock):
        """Passing a list of series IDs sends one request with a repeated
        seriesid[] param covering all of them - the batching the poller
        relies on to avoid one HTTP round-trip per series."""
        mock_response = {
            "data": [
                {
                    "sonarrEpisodeId": 100,
                    "sonarrSeriesId": 1,
                    "title": "Ep A",
                    "subtitles": [],
                    "season": 1,
                    "episode": 1,
                    "path": "/tv/a.mkv",
                    "sceneName": "/tv/a.mkv",
                },
                {
                    "sonarrEpisodeId": 200,
                    "sonarrSeriesId": 2,
                    "title": "Ep B",
                    "subtitles": [],
                    "season": 1,
                    "episode": 1,
                    "path": "/tv/b.mkv",
                    "sceneName": "/tv/b.mkv",
                },
            ],
        }

        respx_mock.get("http://test-bazarr:6767/api/episodes").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_episodes(seriesid=[1, 2])

            assert len(result.data) == 2
            assert len(respx_mock.calls) == 1
            query_string = str(respx_mock.calls[0].request.url.query)
            assert query_string.count("seriesid") == 2

    @pytest.mark.asyncio
    async def test_list_episodes_real_wire_format(self, respx_mock):
        """Bazarr's real /api/episodes has NO top-level `total` at all.

        Unlike /api/series, /api/movies/wanted, and /api/episodes/wanted,
        this endpoint's resource (bazarr/api/episodes/episodes.py) marshals
        with `envelope='data'` only - it never emits `total`. Confirmed
        against a real running Bazarr instance during E2E verification of
        this fix. Also: audio_language items can have null code2/code3
        (same audio_language_model shared across audio_language/subtitles/
        missing_subtitles - the null-code gotcha isn't series-specific) - the
        Episode schema models both fields so this test positively verifies
        they parse, rather than relying on pydantic's default ignore-extras
        to silently drop them.
        """
        mock_response = {
            "data": [
                {
                    "sonarrEpisodeId": 211,
                    "sonarrSeriesId": 1,
                    "title": "Uno",
                    "subtitles": [],
                    "season": 1,
                    "episode": 1,
                    "path": "/tv/Better Call Saul/Season 1/test_video.mp4",
                    "sceneName": None,
                    "audio_language": [
                        {"name": "Unknown", "code2": None, "code3": None}
                    ],
                    "missing_subtitles": [
                        {
                            "name": "French",
                            "code2": "fr",
                            "code3": "fra",
                            "forced": False,
                            "hi": False,
                        }
                    ],
                    "monitored": True,
                }
            ]
        }

        respx_mock.get("http://test-bazarr:6767/api/episodes").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_episodes(seriesid=1)
            assert len(result.data) == 1
            episode = result.data[0]
            assert episode.sonarrEpisodeId == 211
            assert episode.title == "Uno"
            # Null-code audio track parses to SubtitleLanguage with None codes.
            assert len(episode.audio_language) == 1
            assert episode.audio_language[0].name == "Unknown"
            assert episode.audio_language[0].code2 is None
            assert episode.audio_language[0].code3 is None
            # Populated missing_subtitles entry parses cleanly.
            assert len(episode.missing_subtitles) == 1
            assert episode.missing_subtitles[0].code3 == "fra"

    @pytest.mark.asyncio
    async def test_list_episodes_audio_language_null_column(self, respx_mock):
        """A NULL audio_language column marshals as a dict of nulls.

        Same flask-restx `fields.Nested` quirk as
        test_list_all_series_audio_language_null_column, but for episodes:
        Bazarr's postprocess() has no `else` fallback for audio_language, so
        a NULL column reaches marshal as None and comes back as a dict with
        every key null instead of an array. Must normalize to an empty list.
        """
        mock_response = {
            "data": [
                {
                    "sonarrEpisodeId": 211,
                    "sonarrSeriesId": 1,
                    "title": "Uno",
                    "subtitles": [],
                    "season": 1,
                    "episode": 1,
                    "path": "/tv/Better Call Saul/Season 1/test_video.mp4",
                    "sceneName": None,
                    "audio_language": {"name": None, "code2": None, "code3": None},
                    "missing_subtitles": [],
                    "monitored": True,
                }
            ]
        }

        respx_mock.get("http://test-bazarr:6767/api/episodes").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_episodes(seriesid=1)
            assert result.data[0].audio_language == []

    @pytest.mark.asyncio
    async def test_get_episode(self, respx_mock):
        """Test get_episode fetches specific episode by ID."""
        mock_response = {
            "data": [
                {
                    "sonarrEpisodeId": 100,
                    "sonarrSeriesId": 123,
                    "title": "Test Episode",
                    "subtitles": [],
                    "season": 1,
                    "episode": 1,
                    "path": "/tv/Test Series/Season 01/Episode 01.mkv",
                    "sceneName": "/tv/Test Series/Season 01/Episode 01.mkv",
                }
            ],
            "total": 1,
        }

        respx_mock.get("http://test-bazarr:6767/api/episodes").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.get_episode(100)

            assert result is not None
            assert result.sonarrEpisodeId == 100
            assert result.sonarrSeriesId == 123
            assert result.title == "Test Episode"

    @pytest.mark.asyncio
    async def test_get_episode_not_found(self, respx_mock):
        """Test get_episode returns None when episode not found."""
        mock_response = {"data": [], "total": 0}

        respx_mock.get("http://test-bazarr:6767/api/episodes").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.get_episode(999)

            assert result is None
