"""Tests for placeholder-secret refusal (M6.a, security pass)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from audio_to_subs.api.app import create_app
from audio_to_subs.auth.secrets import (
    PLACEHOLDER_SECRET,
    refuse_placeholder_secrets,
)


def _settings(**overrides):
    """Build a stub Settings with non-placeholder secret values."""
    base = {
        "session_secret": "real-session-secret-value-1234567890",
        "mistral_api_key": "real-mistral-key-1234567890",
        "admin_password": "real-admin-password-1234567890",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestRefusePlaceholderSecrets:
    def test_real_secrets_ok(self):
        refuse_placeholder_secrets(_settings())  # must not raise

    def test_session_secret_placeholder_rejected(self):
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            refuse_placeholder_secrets(_settings(session_secret=PLACEHOLDER_SECRET))

    def test_mistral_key_placeholder_rejected(self):
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            refuse_placeholder_secrets(_settings(mistral_api_key="your_api_key_here"))

    def test_admin_password_placeholder_rejected(self):
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            refuse_placeholder_secrets(_settings(admin_password="changeme"))

    def test_none_secrets_ok(self):
        # None values mean "not configured", not placeholder; not rejected here.
        refuse_placeholder_secrets(
            _settings(
                session_secret=None,
                mistral_api_key=None,
                admin_password=None,
            )
        )


class TestLifespanRefusesPlaceholders:
    def test_startup_fails_with_placeholder_mistral_key(self):
        from audio_to_subs.api import app as app_module

        stub = _settings(mistral_api_key="your_api_key_here")
        app = create_app()
        with (
            patch.object(app_module, "get_settings", return_value=stub),
            patch(
                "subprocess.run",
                return_value=SimpleNamespace(returncode=0, stderr="", stdout=""),
            ),
        ):
            with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
                with TestClient(app, raise_server_exceptions=True):
                    pass
