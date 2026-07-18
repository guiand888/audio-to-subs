"""Tests for API wanted endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from audio_to_subs.db.models import BazarrCache, JobLog, JobStatus, LogLevel


class TestWantedItemModel:
    """Test WantedItem model."""

    def test_wanted_item_fields(self):
        """Test that WantedItem has all required fields."""
        from audio_to_subs.api.routes.wanted import WantedItem

        # Check that the model has all expected fields
        fields = WantedItem.model_fields

        assert "id" in fields
        assert "kind" in fields
        assert "ext_id" in fields
        assert "title" in fields
        assert "media_path" in fields
        assert "has_any_subs" in fields
        assert "missing_subtitles" in fields
        assert "last_polled" in fields
        assert "active_job_id" in fields
        assert "active_job_status" in fields
        assert "active_job_progress" in fields


class TestWantedListResponseModel:
    """Test WantedListResponse model."""

    def test_wanted_list_response_fields(self):
        """Test that WantedListResponse has all required fields."""
        from audio_to_subs.api.routes.wanted import WantedListResponse

        fields = WantedListResponse.model_fields

        assert "items" in fields
        assert "total" in fields
        assert "last_refreshed_at" in fields


class TestWantedItemType:
    """Test WantedItemType enum."""

    def test_wanted_item_type_values(self):
        """Test WantedItemType enum values."""
        from audio_to_subs.api.routes.wanted import WantedItemType

        assert WantedItemType.ALL.value == "all"
        assert WantedItemType.MOVIE.value == "movie"
        assert WantedItemType.EPISODE.value == "episode"


class TestListWantedEndpoint:
    """Test GET /api/wanted endpoint."""

    def test_list_wanted_empty(self, authenticated_client):
        """Test list_wanted with empty cache."""
        response = authenticated_client.get("/api/wanted")

        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_list_wanted_with_type_filter(self, authenticated_client):
        """Test list_wanted with type filter."""
        response = authenticated_client.get("/api/wanted?item_type=movie")

        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert "total" in data

    def test_list_wanted_with_pagination(self, authenticated_client):
        """Test list_wanted with pagination."""
        response = authenticated_client.get("/api/wanted?page=1&page_size=50")

        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert "total" in data
        assert len(data["items"]) <= 50

    def test_list_wanted_batches_active_job_status_per_item(
        self, sync_session, authenticated_client
    ):
        """Each item's active_job_status/progress must come from its OWN job.

        Regression test for the N+1 fix: list_wanted used to issue one
        SELECT per item to resolve active job status; it now issues a single
        batched query keyed by job id. This verifies the batching didn't mix
        up which job belongs to which item, and that an item whose job has
        already finished (DONE) correctly shows no active job status.
        """
        from tests.conftest import make_job

        # Distinct media paths so the M6.g duplicate-active guard (unique
        # index on media_path+language_code+output_format for active jobs)
        # doesn't reject the seed rows; the test validates per-item active
        # job status mapping, which is independent of media_path.
        queued_job = make_job(
            status=JobStatus.QUEUED,
            progress_percent=0,
            media_path="/test/video-queued.mp4",
        )
        running_job = make_job(
            status=JobStatus.RUNNING,
            progress_percent=42,
            media_path="/test/video-running.mp4",
        )
        done_job = make_job(
            status=JobStatus.DONE,
            progress_percent=100,
            media_path="/test/video-done.mp4",
        )
        sync_session.add_all([queued_job, running_job, done_job])
        sync_session.flush()

        sync_session.add_all(
            [
                BazarrCache(
                    id="movie:1",
                    kind="movie",
                    ext_id=1,
                    title="Movie One",
                    media_path="/data/movies/one.mkv",
                    has_any_subs=False,
                    missing_subtitles=[],
                    last_polled=datetime.now(timezone.utc),
                    active_job_id=queued_job.id,
                ),
                BazarrCache(
                    id="movie:2",
                    kind="movie",
                    ext_id=2,
                    title="Movie Two",
                    media_path="/data/movies/two.mkv",
                    has_any_subs=False,
                    missing_subtitles=[],
                    last_polled=datetime.now(timezone.utc),
                    active_job_id=running_job.id,
                ),
                BazarrCache(
                    id="movie:3",
                    kind="movie",
                    ext_id=3,
                    title="Movie Three (job finished)",
                    media_path="/data/movies/three.mkv",
                    has_any_subs=False,
                    missing_subtitles=[],
                    last_polled=datetime.now(timezone.utc),
                    active_job_id=done_job.id,
                ),
            ]
        )
        sync_session.commit()

        response = authenticated_client.get("/api/wanted")

        assert response.status_code == 200
        items = {item["id"]: item for item in response.json()["items"]}

        assert items["movie:1"]["active_job_status"] == "queued"
        assert items["movie:1"]["active_job_progress"] == 0

        assert items["movie:2"]["active_job_status"] == "running"
        assert items["movie:2"]["active_job_progress"] == 42

        # done_job isn't QUEUED/RUNNING, so it's excluded by the batched
        # query's status filter, same as before the N+1 fix.
        assert items["movie:3"]["active_job_status"] is None
        assert items["movie:3"]["active_job_progress"] is None

    def _seed_titles(self, sync_session):
        sync_session.add_all(
            [
                BazarrCache(
                    id="movie:1",
                    kind="movie",
                    ext_id=1,
                    title="The Matrix",
                    media_path="/data/movies/matrix.mkv",
                    has_any_subs=False,
                    missing_subtitles=[{"code2": "en"}],
                    last_polled=datetime.now(timezone.utc),
                ),
                BazarrCache(
                    id="movie:2",
                    kind="movie",
                    ext_id=2,
                    title="Matrix Reloaded",
                    media_path="/data/movies/reloaded.mkv",
                    has_any_subs=True,
                    missing_subtitles=[{"code2": "fr"}],
                    last_polled=datetime.now(timezone.utc),
                ),
                BazarrCache(
                    id="episode:1",
                    kind="episode",
                    ext_id=1,
                    title="Breaking Bad S01E01",
                    media_path="/data/series/bb.mkv",
                    has_any_subs=False,
                    missing_subtitles=[{"code2": "en"}],
                    last_polled=datetime.now(timezone.utc),
                ),
            ]
        )
        sync_session.commit()

    def test_list_wanted_search_matches_across_all_pages(
        self, sync_session, authenticated_client
    ):
        """Search must run server-side, not just over the displayed page."""
        self._seed_titles(sync_session)
        response = authenticated_client.get("/api/wanted?search=matrix")
        assert response.status_code == 200
        titles = {i["title"] for i in response.json()["items"]}
        assert titles == {"The Matrix", "Matrix Reloaded"}

    def test_list_wanted_search_is_case_insensitive(
        self, sync_session, authenticated_client
    ):
        self._seed_titles(sync_session)
        response = authenticated_client.get("/api/wanted?search=BREAKING")
        assert response.status_code == 200
        titles = {i["title"] for i in response.json()["items"]}
        assert titles == {"Breaking Bad S01E01"}

    def test_list_wanted_has_any_subs_filter(self, sync_session, authenticated_client):
        self._seed_titles(sync_session)
        response = authenticated_client.get("/api/wanted?has_any_subs=true")
        assert response.status_code == 200
        items = response.json()["items"]
        assert items == [i for i in items if i["has_any_subs"]]
        assert {i["title"] for i in items} == {"Matrix Reloaded"}

    def test_list_wanted_search_composes_with_other_filters(
        self, sync_session, authenticated_client
    ):
        """Search must respect item_type, language, and has_any_subs filters."""
        self._seed_titles(sync_session)
        # "matrix" + Movies + no subs + missing lang en -> only "The Matrix"
        response = authenticated_client.get(
            "/api/wanted?search=matrix&item_type=movie&has_any_subs=false&language=en"
        )
        assert response.status_code == 200
        titles = {i["title"] for i in response.json()["items"]}
        assert titles == {"The Matrix"}


class TestGetWantedItemEndpoint:
    """Test GET /api/wanted/{item_id} endpoint."""

    def test_get_wanted_item_not_found(self, authenticated_client):
        """Test get_wanted_item with nonexistent ID."""
        response = authenticated_client.get("/api/wanted/movie:999999")

        assert response.status_code == 404

    def test_get_wanted_item_with_active_job(self, sync_session, authenticated_client):
        """Test get_wanted_item returns correct item with active job status.

        Verifies that get_wanted_item:
        1. Returns the requested item
        2. Includes active_job_status/progress for QUEUED/RUNNING jobs
        3. Excludes jobs in DONE state (same filter as list_wanted)
        """
        from tests.conftest import make_job

        # Create a running job
        running_job = make_job(status=JobStatus.RUNNING, progress_percent=50)
        sync_session.add(running_job)
        sync_session.flush()

        # Create a cached item with the running job
        sync_session.add(
            BazarrCache(
                id="episode:123",
                kind="episode",
                ext_id=123,
                title="Test Episode",
                media_path="/data/show/s01e01.mkv",
                has_any_subs=False,
                missing_subtitles=[],
                last_polled=datetime.now(timezone.utc),
                active_job_id=running_job.id,
            )
        )
        sync_session.commit()

        response = authenticated_client.get("/api/wanted/episode:123")

        assert response.status_code == 200
        item = response.json()

        assert item["id"] == "episode:123"
        assert item["kind"] == "episode"
        assert item["ext_id"] == 123
        assert item["title"] == "Test Episode"
        assert item["active_job_id"] == running_job.id
        assert item["active_job_status"] == "running"
        assert item["active_job_progress"] == 50

    def test_get_wanted_item_with_finished_job_hidden(
        self, sync_session, authenticated_client
    ):
        """Test get_wanted_item hides DONE jobs (same filter as list_wanted).

        Regression test: both list_wanted and get_wanted_item must filter
        jobs by status (only QUEUED/RUNNING are "active"), so an item pointing
        to a DONE job should show no active_job_status/progress.
        """
        from tests.conftest import make_job

        done_job = make_job(status=JobStatus.DONE, progress_percent=100)
        sync_session.add(done_job)
        sync_session.flush()

        sync_session.add(
            BazarrCache(
                id="movie:999",
                kind="movie",
                ext_id=999,
                title="Finished Movie",
                media_path="/data/movies/finished.mkv",
                has_any_subs=False,
                missing_subtitles=[],
                last_polled=datetime.now(timezone.utc),
                active_job_id=done_job.id,
            )
        )
        sync_session.commit()

        response = authenticated_client.get("/api/wanted/movie:999")

        assert response.status_code == 200
        item = response.json()

        # The item exists
        assert item["id"] == "movie:999"
        # But no active job status is shown (because DONE is filtered out)
        assert item["active_job_status"] is None
        assert item["active_job_progress"] is None


class TestPathTranslation:
    """Test path translation functionality."""

    @pytest.mark.asyncio
    async def test_get_path_map_applies_configured_mapping(self, mock_db_session):
        """_get_path_map must actually load and apply the path_mappings
        setting (regression: B12 — selecting Setting.value_json returns the
        scalar string, and code that then reads `.value_json` off it raises
        AttributeError, silently swallowed, so mappings were never applied).
        """
        import json

        from audio_to_subs.api.routes.wanted import _get_path_map
        from audio_to_subs.db.models import Setting

        mock_db_session.add(
            Setting(
                key="path_mappings",
                value_json=json.dumps(
                    [{"bazarr_prefix": "/data/movies", "local_prefix": "/movies"}]
                ),
            )
        )
        await mock_db_session.flush()
        await mock_db_session.commit()

        path_map = await _get_path_map(mock_db_session)

        assert path_map.translate("/data/movies/foo.mp4") == "/movies/foo.mp4"

    def test_translate_paths(self):
        """Test _translate_paths function."""
        from audio_to_subs.api.routes.wanted import _translate_paths

        # Verify function exists
        assert callable(_translate_paths)


class TestLastRefreshed:
    """Test last refreshed time functionality."""

    def test_get_last_refreshed(self):
        """Test _get_last_refreshed function."""
        from audio_to_subs.api.routes.wanted import _get_last_refreshed

        # Verify function exists
        assert callable(_get_last_refreshed)


class TestWantedRefreshEndpoint:
    """Test POST /api/wanted/refresh endpoint."""

    def test_refresh_endpoint_exists(self, authenticated_client):
        """Test that the refresh endpoint exists and returns success."""
        response = authenticated_client.post("/api/wanted/refresh")

        # The endpoint should exist and return 200
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["started", "completed", "failed"]
        assert "movies_processed" in data
        assert "episodes_processed" in data
        assert isinstance(data["movies_processed"], int)
        assert isinstance(data["episodes_processed"], int)

    def test_refresh_all(self, authenticated_client):
        """Test refresh with all items (default)."""
        response = authenticated_client.post(
            "/api/wanted/refresh", json={"item_type": "all"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["started", "completed", "failed"]
        assert "movies_processed" in data
        assert "episodes_processed" in data
        assert isinstance(data["movies_processed"], int)
        assert isinstance(data["episodes_processed"], int)

    def test_refresh_movies_only(self, authenticated_client):
        """Test refresh with movies only filter."""
        response = authenticated_client.post(
            "/api/wanted/refresh", json={"item_type": "movie"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["started", "completed", "failed"]
        assert "movies_processed" in data
        assert "episodes_processed" in data
        assert isinstance(data["movies_processed"], int)
        assert isinstance(data["episodes_processed"], int)

    def test_refresh_episodes_only(self, authenticated_client):
        """Test refresh with episodes only filter."""
        response = authenticated_client.post(
            "/api/wanted/refresh", json={"item_type": "episode"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["started", "completed", "failed"]
        assert "movies_processed" in data
        assert "episodes_processed" in data
        assert isinstance(data["movies_processed"], int)
        assert isinstance(data["episodes_processed"], int)

    def test_refresh_without_item_type(self, authenticated_client):
        """Test refresh without item_type parameter (should default to all)."""
        response = authenticated_client.post("/api/wanted/refresh")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["started", "completed", "failed"]
        assert "movies_processed" in data
        assert "episodes_processed" in data
        assert isinstance(data["movies_processed"], int)
        assert isinstance(data["episodes_processed"], int)

    def test_refresh_client_init_failure_writes_error_job_log(
        self, authenticated_client, sync_session
    ):
        """If initializing the Bazarr client raises, the failure is persisted
        to the UI's activity log, not just returned in the HTTP response."""
        with patch(
            "audio_to_subs.bazarr.poller.get_bazarr_client_with_settings",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            response = authenticated_client.post("/api/wanted/refresh")

        assert response.status_code == 200
        assert response.json()["status"] == "failed"

        log = sync_session.execute(
            select(JobLog).where(JobLog.level == LogLevel.ERROR)
        ).scalar_one()
        assert log.job_id is None
        assert "Bazarr sync failed" in log.message
