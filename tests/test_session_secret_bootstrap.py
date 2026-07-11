"""Tests for session secret bootstrap: _ensure_session_secret_file() and the
relaxed Settings validator.

These guard against the first-boot crash where SESSION_SECRET_FILE points to a
non-existent file on a fresh volume, SESSION_SECRET is not set, and the old
model_validator raised ValueError before the lifespan could generate the file.

The M6.d security check (M6.d: "Verify the bootstrap refuses to start with
default placeholder secrets") lives here too: the FastAPI lifespan must refuse
to start when SESSION_SECRET resolves to the placeholder value, not just when
the first login request is served.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class TestBootstrapRefusesPlaceholderSecret:
    """M6.d: the bootstrap (lifespan) refuses a placeholder session secret."""

    def test_lifespan_refuses_changeme_secret(self, tmp_path, monkeypatch):
        """SESSION_SECRET=changeme → lifespan raises RuntimeError."""
        import audio_to_subs.api.settings as api_settings
        import audio_to_subs.auth.sessions as auth_sessions
        from audio_to_subs.api.app import create_app

        # Isolate from the autouse test env: force placeholder + no file.
        monkeypatch.setenv("SESSION_SECRET", "changeme")
        monkeypatch.delenv("SESSION_SECRET_FILE", raising=False)
        api_settings._settings = None
        auth_sessions._session_manager = None

        app = create_app()
        with pytest.raises(RuntimeError, match="placeholder"):
            with TestClient(app):
                pass  # entering the context runs the lifespan

    def test_lifespan_accepts_real_secret(self, tmp_path, monkeypatch):
        """A real (non-placeholder) secret lets the lifespan run."""
        import audio_to_subs.api.settings as api_settings
        import audio_to_subs.auth.sessions as auth_sessions
        from audio_to_subs.api.app import create_app

        monkeypatch.setenv("SESSION_SECRET", "a-real-secret-not-a-placeholder")
        monkeypatch.delenv("SESSION_SECRET_FILE", raising=False)
        api_settings._settings = None
        auth_sessions._session_manager = None

        app = create_app()
        with patch(
            "subprocess.run",
            return_value=SimpleNamespace(returncode=0, stderr="", stdout=""),
        ):
            with TestClient(app):
                pass  # no raise → bootstrap accepted the secret


class TestEnsureSessionSecretFile:
    """Tests for _ensure_session_secret_file() in app.py."""

    def test_generates_file_when_missing(self, tmp_path, monkeypatch):
        """A fresh volume: file doesn't exist → file is created."""
        from audio_to_subs.api.app import _ensure_session_secret_file

        monkeypatch.delenv("SESSION_SECRET", raising=False)
        secret_file = tmp_path / "session_secret"
        monkeypatch.setenv("SESSION_SECRET_FILE", str(secret_file))

        assert not secret_file.exists()

        _ensure_session_secret_file()

        assert secret_file.exists()
        content = secret_file.read_text().strip()
        assert len(content) > 0
        assert content != "changeme"

    def test_noop_when_file_already_exists(self, tmp_path, monkeypatch):
        """Existing file is left untouched."""
        from audio_to_subs.api.app import _ensure_session_secret_file

        monkeypatch.delenv("SESSION_SECRET", raising=False)
        secret_file = tmp_path / "session_secret"
        secret_file.write_text("existing-secret-value")
        monkeypatch.setenv("SESSION_SECRET_FILE", str(secret_file))

        _ensure_session_secret_file()

        assert secret_file.read_text().strip() == "existing-secret-value"

    def test_noop_when_session_secret_env_set(self, tmp_path, monkeypatch):
        """When SESSION_SECRET is in the env, the file is irrelevant."""
        from audio_to_subs.api.app import _ensure_session_secret_file

        monkeypatch.setenv("SESSION_SECRET", "my-explicit-secret")
        secret_file = tmp_path / "session_secret"
        monkeypatch.setenv("SESSION_SECRET_FILE", str(secret_file))

        _ensure_session_secret_file()

        assert not secret_file.exists()

    def test_noop_when_neither_set(self, monkeypatch):
        """When neither env var is set, nothing happens (no crash)."""
        from audio_to_subs.api.app import _ensure_session_secret_file

        monkeypatch.delenv("SESSION_SECRET", raising=False)
        monkeypatch.delenv("SESSION_SECRET_FILE", raising=False)

        _ensure_session_secret_file()


class TestSettingsSessionSecretValidator:
    """Tests for the relaxed validate_session_secret_exists validator."""

    def test_allows_file_set_even_if_missing(self, monkeypatch):
        """SESSION_SECRET_FILE set + file missing → no ValueError.

        This is the core fix: the old validator crashed on first boot.
        _ensure_session_secret_file() generates the file before Settings
        runs in production, but the validator must not be a second gate.
        """
        import audio_to_subs.api.settings as api_settings

        api_settings._settings = None

        monkeypatch.delenv("SESSION_SECRET", raising=False)
        monkeypatch.setenv("SESSION_SECRET_FILE", "/nonexistent/path/secret")

        settings = api_settings.get_settings()
        assert settings.SESSION_SECRET is None
        assert settings.SESSION_SECRET_FILE == "/nonexistent/path/secret"

    def test_raises_when_neither_set(self, monkeypatch):
        """Neither SESSION_SECRET nor SESSION_SECRET_FILE → ValueError."""
        import audio_to_subs.api.settings as api_settings

        api_settings._settings = None

        monkeypatch.delenv("SESSION_SECRET", raising=False)
        monkeypatch.delenv("SESSION_SECRET_FILE", raising=False)

        with pytest.raises(ValueError, match="SESSION_SECRET"):
            api_settings.get_settings()

    def test_works_normally_with_explicit_secret(self, monkeypatch):
        """SESSION_SECRET set → validator passes (existing behaviour)."""
        import audio_to_subs.api.settings as api_settings

        api_settings._settings = None

        monkeypatch.setenv("SESSION_SECRET", "explicit-secret-123")
        monkeypatch.delenv("SESSION_SECRET_FILE", raising=False)

        settings = api_settings.get_settings()
        assert settings.SESSION_SECRET == "explicit-secret-123"


class TestCreateAppGeneratesSecretFile:
    """Integration: create_app() generates the secret file on first boot."""

    def test_create_app_generates_secret_on_first_boot(self, tmp_path, monkeypatch):
        """create_app() on a fresh volume generates the file before Settings."""
        import audio_to_subs.api.app as app_module

        # Simulate first-boot: no SESSION_SECRET, file doesn't exist.
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        secret_file = tmp_path / "session_secret"
        monkeypatch.setenv("SESSION_SECRET_FILE", str(secret_file))

        assert not secret_file.exists()

        app = app_module.create_app()

        assert app is not None
        assert secret_file.exists()
        assert secret_file.read_text().strip() != "changeme"
