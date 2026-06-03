"""Tests for API settings endpoints."""

import pytest

from fastapi.testclient import TestClient

from audio_to_subs.api.app import create_app


# ---------------------------------------------------------------------------
# API client fixture (scoped to each test via autouse _test_environment)
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """TestClient backed by the per-test file DB (from _test_environment)."""
    import audio_to_subs.db.base as db_base
    import audio_to_subs.api.settings as api_settings
    import audio_to_subs.auth.sessions as auth_sessions

    db_base._async_engine = None
    api_settings._settings = None
    auth_sessions._session_manager = None

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Settings endpoint tests
# ---------------------------------------------------------------------------

def test_get_settings_empty_db(client):
    """GET /api/settings returns default settings on a fresh database."""
    response = client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()

    assert "mistral_model" in data
    assert "bazarr_poll_interval" in data
    assert "default_language" in data
    assert "default_output_format" in data


def test_get_settings_with_data(client):
    """GET /api/settings returns a valid dict."""
    response = client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "mistral_model" in data
    assert "bazarr_poll_interval" in data


def test_get_single_setting(client):
    """GET /api/settings/{key} returns the setting with its default value."""
    response = client.get("/api/settings/mistral_model")

    assert response.status_code == 200
    data = response.json()

    assert "key" in data
    assert "value" in data
    assert data["key"] == "mistral_model"


def test_get_nonexistent_setting(client):
    """GET /api/settings/{key} returns 404 for unknown keys."""
    response = client.get("/api/settings/nonexistent_key_12345")

    assert response.status_code == 404


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
