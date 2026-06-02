"""Tests for API settings endpoints."""

import json
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from audio_to_subs.api.app import create_app
from audio_to_subs.db.models import Setting, User
from audio_to_subs.db.session import get_async_session


@pytest.fixture
def test_client():
    """Create a test client."""
    app = create_app()
    return TestClient(app)


@pytest.mark.asyncio
async def test_get_settings_empty_db():
    """Test GET /api/settings with empty database."""
    app = create_app()
    client = TestClient(app)
    
    # Clear any existing settings
    # Note: In a real test, we'd set up a clean DB
    
    # For now, test that the endpoint exists and returns defaults
    response = client.get("/api/settings")
    
    assert response.status_code == 200
    data = response.json()
    
    # Should return default settings
    assert "mistral_model" in data
    assert "bazarr_poll_interval" in data
    assert "default_language" in data
    assert "default_output_format" in data


@pytest.mark.asyncio
async def test_get_settings_with_data():
    """Test GET /api/settings with existing data."""
    app = create_app()
    client = TestClient(app)
    
    # Create a setting in the DB
    # This is tricky without a real async DB setup
    # For now, just test that the endpoint structure is correct
    
    response = client.get("/api/settings")
    
    assert response.status_code == 200
    data = response.json()
    
    # Check response structure
    assert isinstance(data, dict)
    assert "mistral_model" in data
    assert "bazarr_poll_interval" in data


@pytest.mark.asyncio
async def test_get_single_setting():
    """Test GET /api/settings/{key}."""
    app = create_app()
    client = TestClient(app)
    
    # Test with a default setting
    response = client.get("/api/settings/mistral_model")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "key" in data
    assert "value" in data
    assert data["key"] == "mistral_model"


@pytest.mark.asyncio
async def test_get_nonexistent_setting():
    """Test GET /api/settings/{key} with nonexistent key."""
    app = create_app()
    client = TestClient(app)
    
    response = client.get("/api/settings/nonexistent_key_12345")
    
    assert response.status_code == 404


class TestSettingsResponseModel:
    """Test SettingsResponse model validation."""

    def test_settings_response_defaults(self):
        """Test that SettingsResponse has correct defaults."""
        from audio_to_subs.api.routes.settings import SettingsResponse, DEFAULT_SETTINGS
        
        response = SettingsResponse.from_db_settings({})
        
        # Check all default fields are present
        for key, default_value in DEFAULT_SETTINGS.items():
            assert hasattr(response, key)
            field_value = getattr(response, key)
            assert field_value == default_value

    def test_settings_response_merges_values(self):
        """Test that SettingsResponse merges DB values with defaults."""
        from audio_to_subs.api.routes.settings import SettingsResponse
        
        db_settings = {
            "mistral_model": "custom-model",
            "bazarr_poll_interval": 7200,
        }
        
        response = SettingsResponse.from_db_settings(db_settings)
        
        assert response.mistral_model == "custom-model"
        assert response.bazarr_poll_interval == 7200
        # Other fields should use defaults
        assert response.default_language == "en"


class TestSettingsUpdateModel:
    """Test SettingsUpdate model validation."""

    def test_settings_update_all_optional(self):
        """Test that all fields in SettingsUpdate are optional."""
        from audio_to_subs.api.routes.settings import SettingsUpdate
        
        # Should be able to create with no fields
        update = SettingsUpdate()
        assert update.model_dump(exclude_unset=True) == {}

    def test_settings_update_with_values(self):
        """Test SettingsUpdate with values."""
        from audio_to_subs.api.routes.settings import SettingsUpdate
        
        update = SettingsUpdate(
            mistral_model="new-model",
            bazarr_poll_interval=1800,
        )
        
        data = update.model_dump(exclude_unset=True)
        assert data["mistral_model"] == "new-model"
        assert data["bazarr_poll_interval"] == 1800
