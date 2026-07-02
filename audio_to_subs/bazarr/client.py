"""Async HTTP client for Bazarr API.

Based on BAZARR_API_RESEARCH.md and the actual Bazarr source code.
"""

import asyncio
import logging
from typing import Any

import httpx

from audio_to_subs.bazarr.schemas import (
    Episode,
    EpisodesPage,
    FileEntry,
    Movie,
    MoviesPage,
    SeriesPage,
    WantedEpisode,
    WantedEpisodesPage,
    WantedMovie,
    WantedMoviesPage,
)

logger = logging.getLogger(__name__)

# Custom exceptions
class BazarrError(Exception):
    """Base exception for Bazarr client errors."""


class BazarrAuthError(BazarrError):
    """Authentication failed with Bazarr API."""


class BazarrNotFoundError(BazarrError):
    """Resource not found in Bazarr API."""


class BazarrRateLimited(BazarrError):
    """Rate limited by Bazarr API."""

    def __init__(self, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after: {retry_after} seconds")


class BazarrServerError(BazarrError):
    """Server error from Bazarr API."""


class BazarrClient:
    """Async HTTP client for Bazarr API.

    Uses httpx.AsyncClient for efficient async HTTP requests.
    Automatically adds X-API-Key header for authentication.
    Implements retry logic for server errors and rate limiting.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
    ) -> None:
        """Initialize BazarrClient.

        Args:
            base_url: Base URL for Bazarr API (e.g., http://bazarr:6767)
            api_key: Bazarr API key
            timeout: Total timeout for requests
            connect_timeout: Connection timeout
            read_timeout: Read timeout
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        # httpx>=0.28 requires either a default or all four params explicitly.
        # Pass timeout as the default and override connect/read individually.
        self.timeout = httpx.Timeout(
            timeout,
            connect=connect_timeout,
            read=read_timeout,
        )
        self._client: httpx.AsyncClient | None = None
        self._headers = {"X-API-Key": api_key}

    async def __aenter__(self) -> "BazarrClient":
        """Async context manager entry."""
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure client is initialized."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=self._headers,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        retry: bool = True,
    ) -> dict[str, Any]:
        """Make a GET request to Bazarr API.

        Args:
            path: API endpoint path (e.g., /api/movies/wanted)
            params: Query parameters
            retry: Whether to retry on server errors

        Returns:
            JSON response as dict

        Raises:
            BazarrAuthError: If authentication fails (401)
            BazarrNotFoundError: If resource not found (404)
            BazarrRateLimited: If rate limited (429)
            BazarrServerError: If server error (5xx) and retry fails
        """
        client = await self._ensure_client()

        try:
            response = await client.get(path, params=params)

            if response.status_code == 401:
                raise BazarrAuthError("Authentication failed: Invalid API key")

            elif response.status_code == 404:
                raise BazarrNotFoundError(f"Resource not found: {path}")

            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                retry_after_seconds = None
                if retry_after:
                    try:
                        retry_after_seconds = int(retry_after)
                    except ValueError:
                        pass
                raise BazarrRateLimited(retry_after=retry_after_seconds)

            elif response.status_code >= 500:
                if retry:
                    logger.warning(
                        "Server error %s on %s, retrying once...",
                        response.status_code,
                        path,
                    )
                    await asyncio.sleep(2)
                    return await self._get(path, params, retry=False)
                else:
                    raise BazarrServerError(
                        f"Server error {response.status_code}: {response.text}"
                    )

            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException as e:
            raise BazarrServerError(f"Request timeout: {e}") from e
        except httpx.RequestError as e:
            raise BazarrServerError(f"Request failed: {e}") from e

    async def _patch(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        retry: bool = True,
    ) -> httpx.Response:
        """Make a PATCH request to Bazarr API.

        Args:
            path: API endpoint path (e.g., /api/movies)
            params: Query parameters
            retry: Whether to retry on server errors

        Returns:
            httpx.Response object (caller checks status code)

        Raises:
            BazarrAuthError: If authentication fails (401)
            BazarrNotFoundError: If resource not found (404)
            BazarrRateLimited: If rate limited (429)
            BazarrServerError: If server error (5xx) and retry fails
        """
        client = await self._ensure_client()

        try:
            response = await client.patch(path, params=params)

            if response.status_code == 401:
                raise BazarrAuthError("Authentication failed: Invalid API key")

            elif response.status_code == 404:
                raise BazarrNotFoundError(f"Resource not found: {path}")

            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                retry_after_seconds = None
                if retry_after:
                    try:
                        retry_after_seconds = int(retry_after)
                    except ValueError:
                        pass
                raise BazarrRateLimited(retry_after=retry_after_seconds)

            elif response.status_code >= 500:
                if retry:
                    logger.warning(
                        "Server error %s on %s, retrying once...",
                        response.status_code,
                        path,
                    )
                    await asyncio.sleep(2)
                    return await self._patch(path, params, retry=False)
                else:
                    raise BazarrServerError(
                        f"Server error {response.status_code}: {response.text}"
                    )

            return response

        except httpx.TimeoutException as e:
            raise BazarrServerError(f"Request timeout: {e}") from e
        except httpx.RequestError as e:
            raise BazarrServerError(f"Request failed: {e}") from e

    # --- Wanted lists (the main listing endpoints) ---

    async def list_wanted_movies(
        self,
        *,
        start: int = 0,
        length: int = -1,
        radarrid: list[int] | None = None,
    ) -> WantedMoviesPage:
        """List movies missing subtitles.

        Args:
            start: Paging start (default 0)
            length: Paging length (default -1 for all)
            radarrid: Filter by specific Radarr IDs

        Returns:
            WantedMoviesPage with list of wanted movies
        """
        params: dict[str, Any] = {"start": start, "length": length}
        if radarrid:
            params["radarrid[]"] = radarrid

        data = await self._get("/api/movies/wanted", params)
        return WantedMoviesPage.model_validate(data)

    async def list_wanted_episodes(
        self,
        *,
        start: int = 0,
        length: int = -1,
        episodeid: list[int] | None = None,
    ) -> WantedEpisodesPage:
        """List episodes missing subtitles.

        Args:
            start: Paging start (default 0)
            length: Paging length (default -1 for all)
            episodeid: Filter by specific episode IDs

        Returns:
            WantedEpisodesPage with list of wanted episodes
        """
        params: dict[str, Any] = {"start": start, "length": length}
        if episodeid:
            params["episodeid[]"] = episodeid

        data = await self._get("/api/episodes/wanted", params)
        return WantedEpisodesPage.model_validate(data)

    # --- Full lists (for the "no subs in any language" filter) ---

    async def list_all_movies(
        self,
        *,
        start: int = 0,
        length: int = -1,
    ) -> MoviesPage:
        """List all movies.

        Args:
            start: Paging start (default 0)
            length: Paging length (default -1 for all)

        Returns:
            MoviesPage with all movies
        """
        params = {"start": start, "length": length}
        data = await self._get("/api/movies", params)
        return MoviesPage.model_validate(data)

    async def list_episodes(
        self,
        *,
        seriesid: int,
    ) -> EpisodesPage:
        """List episodes for a series.

        Args:
            seriesid: Sonarr series ID

        Returns:
            EpisodesPage with episodes for the series
        """
        params = {"seriesid[]": seriesid}
        data = await self._get("/api/episodes", params)
        return EpisodesPage.model_validate(data)

    async def list_all_series(
        self,
        *,
        start: int = 0,
        length: int = -1,
        seriesid: list[int] | None = None,
    ) -> SeriesPage:
        """List all series.

        Args:
            start: Paging start (default 0)
            length: Paging length (default -1 for all)
            seriesid: Filter by specific Sonarr series IDs

        Returns:
            SeriesPage with all series
        """
        params: dict[str, Any] = {"start": start, "length": length}
        if seriesid:
            params["seriesid[]"] = seriesid

        data = await self._get("/api/series", params)
        return SeriesPage.model_validate(data)

    async def get_episode(self, sonarr_episode_id: int) -> Episode | None:
        """Get a specific episode by Sonarr Episode ID.

        Args:
            sonarr_episode_id: Sonarr Episode ID to look up

        Returns:
            Episode object if found, None if no episode matches that ID.

        Raises:
            BazarrAuthError: If authentication fails (401)
            BazarrRateLimited: If rate limited (429)
            BazarrServerError: If server error (5xx) and retry fails
        """
        params = {"episodeid[]": sonarr_episode_id}
        data = await self._get("/api/episodes", params)
        episodes_page = EpisodesPage.model_validate(data)
        if episodes_page.data:
            return episodes_page.data[0]
        return None

    # --- File resolution ---

    async def browse_files(
        self,
        *,
        path: str | None = None,
    ) -> list[FileEntry]:
        """Browse Bazarr file system.

        Args:
            path: Path to browse (default is root)

        Returns:
            List of file/directory entries
        """
        params: dict[str, Any] = {}
        if path is not None:
            params["path"] = path

        data = await self._get("/api/files", params)
        # The API returns a list directly, not wrapped
        if isinstance(data, list):
            return [FileEntry.model_validate(item) for item in data]
        else:
            # Handle the wrapped response if present
            file_data = data.get("data", data)
            if isinstance(file_data, list):
                return [FileEntry.model_validate(item) for item in file_data]
            return []

    # --- Rescan endpoints ---

    async def rescan_movie(self, radarr_id: int) -> bool:
        """Rescan a movie in Bazarr.

        Triggers Bazarr to rescan the movie directory for new subtitle files.
        Uses PATCH /api/movies?radarrid={radarrId}&action=scan-disk endpoint.
        _patch handles retry internally on server errors (5xx).

        Args:
            radarr_id: Radarr ID of the movie to rescan

        Returns:
            True if rescan was triggered successfully, False otherwise
        """
        try:
            response = await self._patch(
                "/api/movies",
                params={"radarrid": radarr_id, "action": "scan-disk"},
            )

            if response.status_code in (200, 201, 202, 204):
                logger.info(
                    "Successfully triggered Bazarr rescan for movie radarr_id=%s",
                    radarr_id,
                )
                return True

            logger.warning(
                "Bazarr rescan for movie %s returned status %s",
                radarr_id,
                response.status_code,
            )
            return False

        except (httpx.RequestError, BazarrError) as e:
            logger.error("Failed to rescan movie %s: %s", radarr_id, e)
            return False

    async def rescan_episode(
        self,
        sonarr_episode_id: int,
        series_id: int | None = None,
    ) -> bool:
        """Rescan an episode in Bazarr.

        Triggers Bazarr to rescan the series directory for new subtitle files.
        Uses PATCH /api/series?seriesid={seriesId}&action=scan-disk endpoint.
        
        Note: Bazarr does NOT support per-episode rescan. Must scan the entire
        series. series_id is required and will be fetched from Bazarr if not provided.
        _patch handles retry internally on server errors (5xx).

        Args:
            sonarr_episode_id: Sonarr Episode ID of the episode to rescan
            series_id: Sonarr Series ID (required - Bazarr only supports series-level scan)

        Returns:
            True if rescan was triggered successfully, False otherwise
        """
        if series_id is None:
            logger.warning(
                "rescan_episode requires series_id. Bazarr only supports series-level scan. "
                "Episode %s cannot be rescanned without series_id.",
                sonarr_episode_id,
            )
            return False

        try:
            response = await self._patch(
                "/api/series",
                params={"seriesid": series_id, "action": "scan-disk"},
            )

            if response.status_code in (200, 201, 202, 204):
                logger.info(
                    "Successfully triggered Bazarr rescan for series series_id=%s "
                    "(containing episode %s)",
                    series_id,
                    sonarr_episode_id,
                )
                return True

            logger.warning(
                "Bazarr rescan for series %s (episode %s) returned status %s",
                series_id,
                sonarr_episode_id,
                response.status_code,
            )
            return False

        except (httpx.RequestError, BazarrError) as e:
            logger.error(
                "Failed to rescan series %s (episode %s): %s",
                series_id,
                sonarr_episode_id,
                e,
            )
            return False

    # --- Utility methods ---

    async def get_movie_by_id(self, radarr_id: int) -> Movie | None:
        """Get a specific movie by Radarr ID.

        Note: This uses the wanted endpoint with filtering since
        Bazarr doesn't have a direct /api/movies/{id} endpoint.
        """
        page = await self.list_all_movies(length=1000)
        for movie in page.data:
            if movie.radarrId == radarr_id:
                return movie
        return None
