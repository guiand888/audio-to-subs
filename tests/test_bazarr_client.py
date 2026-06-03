"""Tests for Bazarr API client."""

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
        """Test 429 rate limited error."""
        respx_mock.get("http://test-bazarr:6767/api/movies/wanted").mock(
            return_value=httpx.Response(429, json={"error": "Rate limited"}, headers={"Retry-After": "30"}),
        )
        
        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            with pytest.raises(BazarrRateLimited) as exc_info:
                await client.list_wanted_movies()
            
            assert exc_info.value.retry_after == 30

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
            result = await client.list_wanted_movies()
            assert result.total == 0


class TestRescanStubs:
    """Test rescan methods (previously stubs, now real HTTP calls)."""

    @pytest.mark.asyncio
    async def test_rescan_movie_stub(self, respx_mock):
        """Test that rescan_movie returns True on 202 response."""
        respx_mock.post("http://test-bazarr:6767/api/movies/123/rescan").mock(
            return_value=httpx.Response(202)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.rescan_movie(123)
            assert result is True

    @pytest.mark.asyncio
    async def test_rescan_episode_stub(self, respx_mock):
        """Test that rescan_episode returns True on 202 response."""
        respx_mock.post("http://test-bazarr:6767/api/episodes/456/rescan").mock(
            return_value=httpx.Response(202)
        )

        async with BazarrClient(
            base_url="http://test-bazarr:6767",
            api_key="test-key",
        ) as client:
            result = await client.rescan_episode(456)
            assert result is True
