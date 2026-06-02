"""Tests for API wanted endpoints."""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from audio_to_subs.api.app import create_app
from audio_to_subs.db.models import BazarrCache, Job, JobStatus, JobSource


@pytest.fixture
def test_client():
    """Create a test client."""
    app = create_app()
    return TestClient(app)


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

    @pytest.mark.asyncio
    async def test_list_wanted_empty(self, test_client):
        """Test list_wanted with empty cache."""
        response = test_client.get("/api/wanted")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_list_wanted_with_type_filter(self, test_client):
        """Test list_wanted with type filter."""
        response = test_client.get("/api/wanted?item_type=movie")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "items" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_list_wanted_with_pagination(self, test_client):
        """Test list_wanted with pagination."""
        response = test_client.get("/api/wanted?page=1&page_size=50")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "items" in data
        assert "total" in data
        assert len(data["items"]) <= 50


class TestGetWantedItemEndpoint:
    """Test GET /api/wanted/{item_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_wanted_item_not_found(self, test_client):
        """Test get_wanted_item with nonexistent ID."""
        response = test_client.get("/api/wanted/movie:999999")
        
        assert response.status_code == 404


class TestPathTranslation:
    """Test path translation functionality."""

    def test_get_path_map(self):
        """Test _get_path_map function."""
        from audio_to_subs.api.routes.wanted import _get_path_map
        from audio_to_subs.bazarr.pathmap import PathMap
        
        # This is an async function that needs a DB session
        # For unit testing, we can just verify the function exists
        assert callable(_get_path_map)

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
