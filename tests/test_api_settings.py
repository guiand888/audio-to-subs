"""Tests for API settings endpoints."""

import pytest


def test_get_settings_empty_db(authenticated_client):
    """GET /api/settings returns default settings on a fresh database."""
    response = authenticated_client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()

    assert "mistral_model" in data
    assert "bazarr_poll_interval" in data
    assert "default_language" in data
    assert "default_output_format" in data


def test_get_settings_with_data(authenticated_client):
    """GET /api/settings returns a valid dict."""
    response = authenticated_client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "mistral_model" in data
    assert "bazarr_poll_interval" in data
    assert "bazarr_url" in data
    assert "bazarr_api_key" in data
    assert "bazarr_timeout" in data


def test_get_single_setting(authenticated_client):
    """GET /api/settings/{key} returns the setting with its default value."""
    response = authenticated_client.get("/api/settings/mistral_model")

    assert response.status_code == 200
    data = response.json()

    assert "key" in data
    assert "value" in data
    assert data["key"] == "mistral_model"


def test_get_nonexistent_setting(authenticated_client):
    """GET /api/settings/{key} returns 404 for unknown keys."""
    response = authenticated_client.get("/api/settings/nonexistent_key_12345")

    assert response.status_code == 404


def test_update_bazarr_settings(authenticated_client, sync_session):
    """PATCH /api/settings can update Bazarr connection settings."""
    # First get current settings
    response = authenticated_client.get("/api/settings")
    assert response.status_code == 200
    response.json()

    # Update Bazarr settings
    update_data = {
        "bazarr_url": "http://test-bazarr:6767",
        "bazarr_api_key": "test-api-key-123",
        "bazarr_timeout": 45.0,
    }

    response = authenticated_client.patch("/api/settings", json=update_data)
    assert response.status_code == 200

    # bazarr_api_key is masked in all API responses (Phase 4.C6); verify the
    # non-secret fields directly and confirm the real value was persisted
    # by reading the DB, not by trusting the (intentionally masked) response.
    updated_data = response.json()
    assert updated_data["bazarr_url"] == "http://test-bazarr:6767"
    assert updated_data["bazarr_api_key"] == "***MASKED***"
    assert updated_data["bazarr_timeout"] == 45.0

    from sqlalchemy import select

    from audio_to_subs.db.models import Setting

    setting = sync_session.execute(
        select(Setting).where(Setting.key == "bazarr_api_key")
    ).scalar_one()
    assert setting.get_value() == "test-api-key-123"

    # Verify the update persisted (non-secret fields via the API)
    response = authenticated_client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["bazarr_url"] == "http://test-bazarr:6767"
    assert data["bazarr_api_key"] == "***MASKED***"
    assert data["bazarr_timeout"] == 45.0


# ---------------------------------------------------------------------------
# Pure model tests (no DB required)
# ---------------------------------------------------------------------------


class TestSettingsResponseModel:
    """Test SettingsResponse model validation."""

    def test_settings_response_defaults(self):
        """SettingsResponse.from_db_settings({}) fills in all defaults."""
        from audio_to_subs.api.routes.settings import DEFAULT_SETTINGS, SettingsResponse

        response = SettingsResponse.from_db_settings({})

        for key, default_value in DEFAULT_SETTINGS.items():
            assert hasattr(response, key)
            assert getattr(response, key) == default_value

    def test_settings_response_includes_bazarr_connection_fields(self):
        """SettingsResponse includes Bazarr connection fields."""
        from audio_to_subs.api.routes.settings import SettingsResponse

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

    def test_bazarr_track_no_subs_removed_from_defaults(self):
        """M8: full sync makes bazarr_track_no_subs redundant - it must be
        gone from the settings schema/defaults entirely, not kept as a
        no-op."""
        from audio_to_subs.api.routes.settings import DEFAULT_SETTINGS

        assert "bazarr_track_no_subs" not in DEFAULT_SETTINGS

    def test_bazarr_track_no_subs_removed_from_response_model(self):
        from audio_to_subs.api.routes.settings import SettingsResponse

        assert "bazarr_track_no_subs" not in SettingsResponse.model_fields

    def test_bazarr_track_no_subs_removed_from_update_model(self):
        from audio_to_subs.api.routes.settings import SettingsUpdate

        assert "bazarr_track_no_subs" not in SettingsUpdate.model_fields

    def test_get_settings_response_has_no_track_no_subs_field(
        self, authenticated_client
    ):
        """End-to-end: the field must not appear on the wire either."""
        response = authenticated_client.get("/api/settings")
        assert response.status_code == 200
        assert "bazarr_track_no_subs" not in response.json()


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


class TestTimezoneSetting:
    """Tests for the user-configurable timezone setting."""

    def test_timezone_in_defaults(self):
        """timezone is part of DEFAULT_SETTINGS with a UTC default."""
        from audio_to_subs.api.routes.settings import DEFAULT_SETTINGS

        assert "timezone" in DEFAULT_SETTINGS
        assert DEFAULT_SETTINGS["timezone"] == "UTC"

    def test_settings_response_includes_timezone(self):
        """SettingsResponse exposes a timezone field."""
        from audio_to_subs.api.routes.settings import SettingsResponse

        response = SettingsResponse.from_db_settings({})
        assert hasattr(response, "timezone")
        assert response.timezone == "UTC"

    def test_settings_response_merges_timezone(self):
        """SettingsResponse merges a DB-stored timezone over the default."""
        from audio_to_subs.api.routes.settings import SettingsResponse

        response = SettingsResponse.from_db_settings({"timezone": "Europe/Paris"})
        assert response.timezone == "Europe/Paris"

    def test_settings_update_accepts_valid_timezone(self):
        """SettingsUpdate accepts a valid IANA timezone string."""
        from audio_to_subs.api.routes.settings import SettingsUpdate

        update = SettingsUpdate(timezone="America/New_York")
        data = update.model_dump(exclude_unset=True)
        assert data["timezone"] == "America/New_York"

    def test_settings_update_rejects_invalid_timezone(self):
        """SettingsUpdate rejects a non-existent IANA timezone (422)."""
        from pydantic import ValidationError

        from audio_to_subs.api.routes.settings import SettingsUpdate

        with pytest.raises(ValidationError):
            SettingsUpdate(timezone="Not/A/Real_Zone")

    def test_get_settings_returns_timezone(self, authenticated_client):
        """GET /api/settings returns the timezone field with its default."""
        response = authenticated_client.get("/api/settings")
        assert response.status_code == 200
        assert response.json()["timezone"] == "UTC"

    def test_patch_settings_persists_timezone(self, authenticated_client):
        """PATCH /api/settings persists and round-trips the timezone."""
        response = authenticated_client.patch(
            "/api/settings", json={"timezone": "Europe/Paris"}
        )
        assert response.status_code == 200
        assert response.json()["timezone"] == "Europe/Paris"

        # Re-read to confirm persistence
        response = authenticated_client.get("/api/settings")
        assert response.json()["timezone"] == "Europe/Paris"

    def test_patch_settings_rejects_invalid_timezone(self, authenticated_client):
        """PATCH /api/settings with an invalid timezone returns 422."""
        response = authenticated_client.patch(
            "/api/settings", json={"timezone": "Bogus/Zone"}
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# BAZARR_API_KEY_FILE tests
# ---------------------------------------------------------------------------


class TestBazarrApiKeyFile:
    """Test BAZARR_API_KEY_FILE loading functionality."""

    def test_bazarr_api_key_from_env(self, monkeypatch):
        """Test BAZARR_API_KEY loaded directly from environment."""
        # Reset settings
        import audio_to_subs.api.settings as api_settings
        from audio_to_subs.api.settings import get_settings

        api_settings._settings = None

        monkeypatch.setenv("BAZARR_API_KEY", "direct-key-123")
        monkeypatch.setenv("BAZARR_API_KEY_FILE", "")

        settings = get_settings()
        assert settings.BAZARR_API_KEY == "direct-key-123"
        assert settings.bazarr_api_key == "direct-key-123"

    def test_bazarr_api_key_from_file(self, monkeypatch, tmp_path):
        """Test BAZARR_API_KEY loaded from file."""
        # Reset settings
        import audio_to_subs.api.settings as api_settings
        from audio_to_subs.api.settings import get_settings

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
        # Reset settings
        import audio_to_subs.api.settings as api_settings
        from audio_to_subs.api.settings import get_settings

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
        # Reset settings
        import audio_to_subs.api.settings as api_settings
        from audio_to_subs.api.settings import get_settings

        api_settings._settings = None

        monkeypatch.delenv("BAZARR_API_KEY", raising=False)
        monkeypatch.setenv("BAZARR_API_KEY_FILE", "/nonexistent/path/key.txt")

        settings = get_settings()
        assert settings.BAZARR_API_KEY is None
        assert settings.BAZARR_API_KEY_FILE == "/nonexistent/path/key.txt"
        assert settings.bazarr_api_key is None


class TestBazarrConnectionTestEndpoint:
    """Test the Bazarr connection test endpoint."""

    def test_connection_test_endpoint_exists(self, authenticated_client):
        """Test that the connection test endpoint exists and returns appropriate response."""
        # Without configuring Bazarr, the endpoint should still exist
        # and return an appropriate response
        response = authenticated_client.post("/api/settings/test-bazarr-connection")

        # The endpoint should exist and return 200
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "error" in data
        # Without Bazarr configured, should return success=False with error
        assert data["success"] is False
        assert data["error"] == "bazarr_not_configured"

    def test_connection_test_with_configured_settings(self, authenticated_client):
        """Test connection test with Bazarr settings configured."""
        # Configure Bazarr settings
        update_data = {
            "bazarr_url": "http://localhost:6767",
            "bazarr_api_key": "test-api-key-123",
        }
        authenticated_client.patch("/api/settings", json=update_data)

        # Test the connection - will likely fail without real Bazarr,
        # but endpoint should exist and return structured response
        response = authenticated_client.post("/api/settings/test-bazarr-connection")

        # Should return 200 with structured response
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "error" in data
        assert "message" in data
        # Will likely fail without real Bazarr instance
        assert isinstance(data["success"], bool)
        assert isinstance(data["error"], str) or data["error"] is None

    def test_connection_test_uses_request_overrides_not_saved_settings(
        self, authenticated_client
    ):
        """Passing bazarr_url in the body should test those values, not saved settings."""
        # Save one (empty/unconfigured) set of settings.
        authenticated_client.patch(
            "/api/settings",
            json={"bazarr_url": "", "bazarr_api_key": ""},
        )

        # Without an override, the saved (empty) settings mean Bazarr isn't configured.
        response = authenticated_client.post("/api/settings/test-bazarr-connection")
        assert response.json()["error"] == "bazarr_not_configured"

        # With an override in the body, the endpoint should attempt to use it
        # instead of reporting "not configured" from the saved settings.
        response = authenticated_client.post(
            "/api/settings/test-bazarr-connection",
            json={
                "bazarr_url": "http://localhost:6767",
                "bazarr_api_key": "unsaved-key",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["error"] != "bazarr_not_configured"


class TestBazarrConnectionTestWireBehavior:
    """Drive test-bazarr-connection against Bazarr's REAL wire format.

    Unlike the tests above (which never mock Bazarr at the HTTP level and so
    can't tell a genuine connectivity failure from a schema mismatch), these
    use respx to intercept the outbound BazarrClient request and return
    exactly what a real Bazarr instance sends - reverse-engineered from
    Bazarr's source (see tests/bazarr_fixtures.py). Body overrides are used
    so each test is hermetic (skips DB/env resolution entirely).
    """

    def test_success_with_realistic_payload(self, authenticated_client, respx_mock):
        """A valid key against a real Bazarr response must report success."""
        import httpx

        from tests.bazarr_fixtures import realistic_series_item

        route = respx_mock.get("http://bazarr-wire-test:6767/api/series").mock(
            return_value=httpx.Response(
                200, json={"data": [realistic_series_item()], "total": 458}
            )
        )

        response = authenticated_client.post(
            "/api/settings/test-bazarr-connection",
            json={
                "bazarr_url": "http://bazarr-wire-test:6767",
                "bazarr_api_key": "wire-test-key",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["error"] is None

        assert route.called
        sent = route.calls[0].request
        assert sent.headers["X-API-Key"] == "wire-test-key"
        assert "length=1" in str(sent.url.query)

    def test_wrong_key_401_html_body(self, authenticated_client, respx_mock):
        """A real Bazarr 401 is an HTML (Werkzeug) body, not JSON."""
        import httpx

        respx_mock.get("http://bazarr-wire-test:6767/api/series").mock(
            return_value=httpx.Response(
                401,
                text="<!doctype html><title>401 Unauthorized</title>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )

        response = authenticated_client.post(
            "/api/settings/test-bazarr-connection",
            json={
                "bazarr_url": "http://bazarr-wire-test:6767",
                "bazarr_api_key": "wrong-key",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "authentication_failed"

    def test_bad_path_302_redirect_to_frontend(self, authenticated_client, respx_mock):
        """An unmatched path (e.g. wrong base_url) 302s to Bazarr's HTML index.

        Bazarr's global 404 handler redirects to `base_url` instead of
        returning a JSON 404 (see bazarr/app/app.py). BazarrClient doesn't
        follow redirects, so `raise_for_status()` raises for the unfollowed
        3xx and the endpoint reports a generic connection failure.
        """
        import httpx

        respx_mock.get("http://bazarr-wire-test:6767/api/series").mock(
            return_value=httpx.Response(
                302,
                headers={
                    "location": "http://bazarr-wire-test:6767/",
                    "content-type": "text/html; charset=utf-8",
                },
                text="<!doctype html><title>Redirecting...</title>",
            )
        )

        response = authenticated_client.post(
            "/api/settings/test-bazarr-connection",
            json={
                "bazarr_url": "http://bazarr-wire-test:6767",
                "bazarr_api_key": "wire-test-key",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "connection_failed"

    def test_success_with_empty_library(self, authenticated_client, respx_mock):
        """An empty Bazarr library is a valid, successful response."""
        import httpx

        respx_mock.get("http://bazarr-wire-test:6767/api/series").mock(
            return_value=httpx.Response(200, json={"data": [], "total": 0})
        )

        response = authenticated_client.post(
            "/api/settings/test-bazarr-connection",
            json={
                "bazarr_url": "http://bazarr-wire-test:6767",
                "bazarr_api_key": "wire-test-key",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_schema_drift_maps_to_unexpected_response(
        self, authenticated_client, respx_mock
    ):
        """Genuine schema drift must be distinguishable from connectivity failure.

        This uses the OLD (wrong) wire assumption - audio_language as a
        populated dict, never seen from a real Bazarr - to prove drift is
        still caught and reported distinctly, not silently accepted.
        """
        import httpx

        from tests.bazarr_fixtures import realistic_series_item

        drifted_item = realistic_series_item(
            audio_language={"name": "English", "code2": "en", "code3": "eng"}
        )
        respx_mock.get("http://bazarr-wire-test:6767/api/series").mock(
            return_value=httpx.Response(200, json={"data": [drifted_item], "total": 1})
        )

        response = authenticated_client.post(
            "/api/settings/test-bazarr-connection",
            json={
                "bazarr_url": "http://bazarr-wire-test:6767",
                "bazarr_api_key": "wire-test-key",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "unexpected_response"
