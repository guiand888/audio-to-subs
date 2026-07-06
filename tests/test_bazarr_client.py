"""Tests for Bazarr API client."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from audio_to_subs.bazarr.client import (
    BazarrClient,
    BazarrAuthError,
    BazarrNotFoundError,
    BazarrRateLimited,
    BazarrServerError,
    BazarrError,
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
    """Test client HTTP requests with respx."""

    @pytest.mark.asyncio
    async def test_list_wanted_movies(self, respx_mock):
        """Test list_wanted_movies endpoint."""
        # Mock the API response
        mock_response = {
            "data": [
                {
                    "title": "Inception",
                    "missing_subtitles": [
                        {"name": "English", "code2": "en", "code3": "eng", "forced": False, "hi": False}
                    ],
                    "radarrId": 123,
                    "sceneName": "/movies/Inception.mkv",
                    "tags": ["action", "sci-fi"],
                }
            ],
            "total": 1,
        }
        
        respx_mock.get("http://test-bazarr:6767/api/movies/wanted").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_wanted_movies()

            assert result.total == 1
            assert len(result.data) == 1
            assert result.data[0].title == "Inception"
            assert result.data[0].radarrId == 123

    @pytest.mark.asyncio
    async def test_list_wanted_episodes(self, respx_mock):
        """Test list_wanted_episodes endpoint."""
        mock_response = {
            "data": [
                {
                    "seriesTitle": "Test Show",
                    "episode_number": "1x01",
                    "episodeTitle": "Pilot",
                    "missing_subtitles": [
                        {"name": "French", "code2": "fr", "code3": "fre", "forced": False, "hi": False}
                    ],
                    "sonarrSeriesId": 456,
                    "sonarrEpisodeId": 789,
                    "sceneName": "/tv/Test Show/Pilot.mkv",
                    "tags": ["drama"],
                    "seriesType": "standard",
                }
            ],
            "total": 1,
        }
        
        respx_mock.get("http://test-bazarr:6767/api/episodes/wanted").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.list_wanted_episodes()
            
            assert result.total == 1
            assert len(result.data) == 1
            assert result.data[0].seriesTitle == "Test Show"
            assert result.data[0].sonarrEpisodeId == 789

    @pytest.mark.asyncio
    async def test_auth_error(self, respx_mock):
        """Test 401 authentication error."""
        respx_mock.get("http://test-bazarr:6767/api/movies/wanted").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"}),
        )
        
        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="wrong-key",
        ) as client:
            with pytest.raises(BazarrAuthError):
                await client.list_wanted_movies()

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
        route = respx_mock.get("http://test-bazarr:6767/api/movies/wanted").mock(
            return_value=httpx.Response(429, json={"error": "Rate limited"}, headers={"Retry-After": "30"}),
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            with patch(
                "audio_to_subs.bazarr.client.asyncio.sleep", new=AsyncMock()
            ) as mock_sleep:
                with pytest.raises(BazarrRateLimited) as exc_info:
                    await client.list_wanted_movies()

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
        route = respx_mock.get("http://test-bazarr:6767/api/movies/wanted")
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
                result = await client.list_wanted_movies()

                assert result.total == 0
                assert route.call_count == 2
                mock_sleep.assert_awaited_once_with(5)

    @pytest.mark.asyncio
    async def test_server_error_with_retry(self, respx_mock):
        """Test 5xx server error with retry."""
        # First request fails with 500, second succeeds — use httpx.Response explicitly.
        respx_mock.get("http://test-bazarr:6767/api/movies/wanted").side_effect = [
            httpx.Response(500, json={"error": "Server error"}),
            httpx.Response(200, json={"data": [], "total": 0}),
        ]

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            with patch("audio_to_subs.bazarr.client.asyncio.sleep", new=AsyncMock()):
                result = await client.list_wanted_movies()
                assert result.total == 0

    @pytest.mark.asyncio
    async def test_server_error_exponential_backoff(self, respx_mock):
        """Test that repeated 5xx errors (no Retry-After) back off exponentially."""
        route = respx_mock.get("http://test-bazarr:6767/api/movies/wanted")
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
                result = await client.list_wanted_movies()

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
        route = respx_mock.get("http://test-bazarr:6767/api/movies/wanted").mock(
            return_value=httpx.Response(500, json={"error": "Server error"}),
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
            max_retries=2,
        ) as client:
            with patch("audio_to_subs.bazarr.client.asyncio.sleep", new=AsyncMock()):
                with pytest.raises(BazarrServerError):
                    await client.list_wanted_movies()

                assert route.call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_backoff_capped_at_backoff_max(self, respx_mock):
        """Test that a large Retry-After value is capped at backoff_max."""
        route = respx_mock.get("http://test-bazarr:6767/api/movies/wanted")
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
                result = await client.list_wanted_movies()

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


class TestSeries:
    """Test series endpoint."""

    @pytest.mark.asyncio
    async def test_list_all_series(self, respx_mock):
        """Test list_all_series returns SeriesPage."""
        mock_response = {
            "data": [
                {
                    "sonarrSeriesId": 123,
                    "title": "Test Series",
                    "path": "/tv/Test Series",
                    "tvdbId": 456,
                    "imdbId": "tt1234567",
                    "monitored": True,
                    "profileId": 1,
                    "seriesType": "standard",
                    "tags": [],
                    "alternativeTitles": [],
                    "ended": False,
                    "lastAired": None,
                    "fanart": None,
                    "poster": None,
                    "overview": "Test overview",
                    "year": "2024",
                    "audio_language": {},
                }
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
            assert len(result.data) == 1
            assert result.total == 1
            assert result.data[0].sonarrSeriesId == 123
            assert result.data[0].title == "Test Series"

    @pytest.mark.asyncio
    async def test_list_episodes(self, respx_mock):
        """Test list_episodes uses seriesid[] parameter."""
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
            result = await client.list_episodes(seriesid=123)
            
            assert len(result.data) == 1
            assert result.total == 1
            assert result.data[0].sonarrEpisodeId == 100
            assert result.data[0].sonarrSeriesId == 123
            # Verify the request was made with correct parameter name
            assert len(respx_mock.calls) == 1
            query_string = str(respx_mock.calls[0].request.url.query)
            # seriesid[] is URL-encoded as seriesid%5B%5D
            assert "seriesid%5B%5D" in query_string or "seriesid[]" in query_string

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
