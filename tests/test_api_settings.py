"""Tests for API settings endpoints."""

import pytest


def test_get_settings_empty_db(api_client):
    """GET /api/settings returns default settings on a fresh database."""
    response = api_client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()

    assert "mistral_model" in data
    assert "bazarr_poll_interval" in data
    assert "default_language" in data
    assert "default_output_format" in data


def test_get_settings_with_data(api_client):
    """GET /api/settings returns a valid dict."""
    response = api_client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "mistral_model" in data
    assert "bazarr_poll_interval" in data
    assert "bazarr_url" in data
    assert "bazarr_api_key" in data
    assert "bazarr_timeout" in data


def test_get_single_setting(api_client):
    """GET /api/settings/{key} returns the setting with its default value."""
    response = api_client.get("/api/settings/mistral_model")

    assert response.status_code == 200
    data = response.json()

    assert "key" in data
    assert "value" in data
    assert data["key"] == "mistral_model"


def test_get_nonexistent_setting(api_client):
    """GET /api/settings/{key} returns 404 for unknown keys."""
    response = api_client.get("/api/settings/nonexistent_key_12345")

    assert response.status_code == 404


def test_update_bazarr_settings(api_client):
    """PATCH /api/settings can update Bazarr connection settings."""
    # First get current settings
    response = api_client.get("/api/settings")
    assert response.status_code == 200
    original_data = response.json()

    # Update Bazarr settings
    update_data = {
        "bazarr_url": "http://test-bazarr:6767",
        "bazarr_api_key": "test-api-key-123",
        "bazarr_timeout": 45.0
    }

    response = api_client.patch("/api/settings", json=update_data)
    assert response.status_code == 200

    updated_data = response.json()
    assert updated_data["bazarr_url"] == "http://test-bazarr:6767"
    assert updated_data["bazarr_api_key"] == "test-api-key-123"
    assert updated_data["bazarr_timeout"] == 45.0
    
    # Verify the update persisted
    response = api_client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["bazarr_url"] == "http://test-bazarr:6767"
    assert data["bazarr_api_key"] == "test-api-key-123"
    assert data["bazarr_timeout"] == 45.0


# ---------------------------------------------------------------------------
# Pure model tests (no DB required)
# ---------------------------------------------------------------------------

class TestSettingsResponseModel:
    """Test SettingsResponse model validation."""

    def test_settings_response_defaults(self):
        """SettingsResponse.from_db_settings({}) fills in all defaults."""
        from audio_to_subs.api.routes.settings import SettingsResponse, DEFAULT_SETTINGS

        response = SettingsResponse.from_db_settings({})

        for key, default_value in DEFAULT_SETTINGS.items():
            assert hasattr(response, key)
            assert getattr(response, key) == default_value

    def test_settings_response_includes_bazarr_connection_fields(self):
        """SettingsResponse includes Bazarr connection fields."""
        from audio_to_subs.api.routes.settings import SettingsResponse, DEFAULT_SETTINGS

        response = SettingsResponse.from_db_settings({})

        # Check that Bazarr connection fields are present with correct defaults
        assert hasattr(response, "bazarr_url")
        assert hasattr(response, "bazarr_api_key")
        assert hasattr(response, "bazarr_timeout")
        assert response.bazarr_url is None
        assert response.bazarr_api_key is None
        assert response.bazarr_timeout == 30.0

    def test_settings_response_merges_values(self):
        """SettingsResponse merges DB values with defaults."""
        from audio_to_subs.api.routes.settings import SettingsResponse

        db_settings = {
            "mistral_model": "custom-model",
            "bazarr_poll_interval": 7200,
        }

        response = SettingsResponse.from_db_settings(db_settings)

        assert response.mistral_model == "custom-model"
        assert response.bazarr_poll_interval == 7200
        assert response.default_language == "en"


class TestSettingsUpdateModel:
    """Test SettingsUpdate model validation."""

    def test_settings_update_all_optional(self):
        """All fields in SettingsUpdate are optional."""
        from audio_to_subs.api.routes.settings import SettingsUpdate

        update = SettingsUpdate()
        assert update.model_dump(exclude_unset=True) == {}

    def test_settings_update_with_values(self):
        """SettingsUpdate serialises correctly."""
        from audio_to_subs.api.routes.settings import SettingsUpdate

        update = SettingsUpdate(
            mistral_model="new-model",
            bazarr_poll_interval=1800,
        )

        data = update.model_dump(exclude_unset=True)
        assert data["mistral_model"] == "new-model"
        assert data["bazarr_poll_interval"] == 1800

    def test_settings_update_with_bazarr_connection_fields(self):
        """SettingsUpdate supports Bazarr connection fields."""
        from audio_to_subs.api.routes.settings import SettingsUpdate

        update = SettingsUpdate(
            bazarr_url="http://test-bazarr:6767",
            bazarr_api_key="test-api-key",
            bazarr_timeout=60.0,
        )

        data = update.model_dump(exclude_unset=True)
        assert data["bazarr_url"] == "http://test-bazarr:6767"
        assert data["bazarr_api_key"] == "test-api-key"
        assert data["bazarr_timeout"] == 60.0


# ---------------------------------------------------------------------------
# BAZARR_API_KEY_FILE tests
# ---------------------------------------------------------------------------

class TestBazarrApiKeyFile:
    """Test BAZARR_API_KEY_FILE loading functionality."""

    def test_bazarr_api_key_from_env(self, monkeypatch):
        """Test BAZARR_API_KEY loaded directly from environment."""
        from audio_to_subs.api.settings import Settings, get_settings
        
        # Reset settings
        import audio_to_subs.api.settings as api_settings
        api_settings._settings = None
        
        monkeypatch.setenv("BAZARR_API_KEY", "direct-key-123")
        monkeypatch.setenv("BAZARR_API_KEY_FILE", "")
        
        settings = get_settings()
        assert settings.BAZARR_API_KEY == "direct-key-123"
        assert settings.bazarr_api_key == "direct-key-123"

    def test_bazarr_api_key_from_file(self, monkeypatch, tmp_path):
        """Test BAZARR_API_KEY loaded from file."""
        from audio_to_subs.api.settings import Settings, get_settings
        
        # Reset settings
        import audio_to_subs.api.settings as api_settings
        api_settings._settings = None
        
        # Create a temporary file with API key
        api_key_file = tmp_path / "bazarr_key.txt"
        api_key_file.write_text("file-key-456\n")

        # Unset (not empty-string) mirrors how a real deployment omits the var;
        # the *_FILE fallback validators only trigger on None, matching the
        # existing MISTRAL_API_KEY_FILE/SESSION_SECRET_FILE convention.
        monkeypatch.delenv("BAZARR_API_KEY", raising=False)
        monkeypatch.setenv("BAZARR_API_KEY_FILE", str(api_key_file))
        
        settings = get_settings()
        # The mode="before" field_validator populates BAZARR_API_KEY itself
        # from the file (same as the pre-existing MISTRAL_API_KEY_FILE pattern).
        assert settings.BAZARR_API_KEY == "file-key-456"
        assert settings.BAZARR_API_KEY_FILE == str(api_key_file)
        assert settings.bazarr_api_key == "file-key-456"

    def test_bazarr_api_key_env_takes_priority(self, monkeypatch, tmp_path):
        """Test BAZARR_API_KEY from env takes priority over file."""
        from audio_to_subs.api.settings import Settings, get_settings
        
        # Reset settings
        import audio_to_subs.api.settings as api_settings
        api_settings._settings = None
        
        # Create a temporary file with API key
        api_key_file = tmp_path / "bazarr_key.txt"
        api_key_file.write_text("file-key-789\n")
        
        monkeypatch.setenv("BAZARR_API_KEY", "env-key-priority")
        monkeypatch.setenv("BAZARR_API_KEY_FILE", str(api_key_file))
        
        settings = get_settings()
        assert settings.BAZARR_API_KEY == "env-key-priority"
        assert settings.bazarr_api_key == "env-key-priority"

    def test_bazarr_api_key_file_not_found(self, monkeypatch):
        """Test BAZARR_API_KEY_FILE returns None when file not found."""
        from audio_to_subs.api.settings import Settings, get_settings
        
        # Reset settings
        import audio_to_subs.api.settings as api_settings
        api_settings._settings = None
        
        monkeypatch.delenv("BAZARR_API_KEY", raising=False)
        monkeypatch.setenv("BAZARR_API_KEY_FILE", "/nonexistent/path/key.txt")
        
        settings = get_settings()
        assert settings.BAZARR_API_KEY is None
        assert settings.BAZARR_API_KEY_FILE == "/nonexistent/path/key.txt"
        assert settings.bazarr_api_key is None


class TestBazarrConnectionTestEndpoint:
    """Test the Bazarr connection test endpoint."""

    def test_connection_test_endpoint_exists(self, client):
        """Test that the connection test endpoint exists and returns appropriate response."""
        # Without configuring Bazarr, the endpoint should still exist
        # and return an appropriate response
        response = api_client.post("/api/settings/test-bazarr-connection")
        
        # The endpoint should exist and return 200
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "error" in data
        # Without Bazarr configured, should return success=False with error
        assert data["success"] is False
        assert data["error"] == "bazarr_not_configured"

    def test_connection_test_with_configured_settings(self, client):
        """Test connection test with Bazarr settings configured."""
        # Configure Bazarr settings
        update_data = {
            "bazarr_url": "http://localhost:6767",
            "bazarr_api_key": "test-api-key-123",
        }
        api_client.patch("/api/settings", json=update_data)
        
        # Test the connection - will likely fail without real Bazarr,
        # but endpoint should exist and return structured response
        response = api_client.post("/api/settings/test-bazarr-connection")
        
        # Should return 200 with structured response
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "error" in data
        assert "message" in data
        # Will likely fail without real Bazarr instance
        assert isinstance(data["success"], bool)
        assert isinstance(data["error"], str) or data["error"] is None

    def test_connection_test_uses_request_overrides_not_saved_settings(self, client):
        """Passing bazarr_url in the body should test those values, not saved settings."""
        # Save one (empty/unconfigured) set of settings.
        api_client.patch(
            "/api/settings",
            json={"bazarr_url": "", "bazarr_api_key": ""},
        )

        # Without an override, the saved (empty) settings mean Bazarr isn't configured.
        response = api_client.post("/api/settings/test-bazarr-connection")
        assert response.json()["error"] == "bazarr_not_configured"

        # With an override in the body, the endpoint should attempt to use it
        # instead of reporting "not configured" from the saved settings.
        response = api_client.post(
            "/api/settings/test-bazarr-connection",
            json={
                "bazarr_url": "http://localhost:6767",
                "bazarr_api_key": "unsaved-key",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["error"] != "bazarr_not_configured"
