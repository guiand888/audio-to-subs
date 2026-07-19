"""Regression test: secrets must never appear in logs or API responses.

Covers MILESTONES.md M6 security item "Confirm secrets never appear in logs"
and the related "Verify the bootstrap refuses to start with default placeholder
secrets" intent of keeping credentials out of observability surfaces.

The test sets distinctive sentinel secrets via env vars, exercises the auth and
settings surfaces, and asserts neither the secrets nor the admin password ever
reach the logging stream or a settings response body.
"""

import logging

import pytest

SENTINEL_MISTRAL = "sk-mistral-SENTINEL-do-not-leak-0001"
SENTINEL_BAZARR = "bazarr-SENTINEL-do-not-leak-0002"
SENTINEL_SESSION = "session-SENTINEL-do-not-leak-0003"
# The admin password seeded by conftest's _test_environment fixture.
CONFTEST_ADMIN_PW = "test-secure-password-12345"


@pytest.fixture
def secret_environment(monkeypatch):
    """Point secrets at distinctive sentinels via env vars.

    The settings singleton is reset by the ``authenticated_client`` fixture's
    nested ``api_client`` setup, so the app reads these values on boot.
    """
    monkeypatch.setenv("MISTRAL_API_KEY", SENTINEL_MISTRAL)
    monkeypatch.setenv("BAZARR_API_KEY", SENTINEL_BAZARR)
    monkeypatch.setenv("SESSION_SECRET", SENTINEL_SESSION)
    monkeypatch.setenv("BAZARR_URL", "http://bazarr:6769")
    yield


def _assert_no_secret_in_logs(records, *secrets: str) -> None:
    joined = "\n".join(record.getMessage() for record in records)
    for secret in secrets:
        assert secret not in joined, f"Secret leaked into logs: {secret!r}"


def test_secrets_not_in_logs_on_login_and_settings(
    secret_environment, authenticated_client, caplog
):
    with caplog.at_level(logging.DEBUG):
        # Re-login (the fixture already logged in once) and fetch settings.
        authenticated_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": CONFTEST_ADMIN_PW},
        )
        resp = authenticated_client.get("/api/settings")
        assert resp.status_code == 200
    _assert_no_secret_in_logs(
        caplog.records,
        SENTINEL_MISTRAL,
        SENTINEL_BAZARR,
        SENTINEL_SESSION,
        CONFTEST_ADMIN_PW,
    )


def test_secrets_masked_in_settings_response(secret_environment, authenticated_client):
    resp = authenticated_client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.text
    for secret in (
        SENTINEL_MISTRAL,
        SENTINEL_BAZARR,
        SENTINEL_SESSION,
        CONFTEST_ADMIN_PW,
    ):
        assert secret not in body


def test_failed_login_does_not_log_password(secret_environment, api_client, caplog):
    with caplog.at_level(logging.DEBUG):
        resp = api_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "definitely-wrong-password"},
        )
        assert resp.status_code == 401
    _assert_no_secret_in_logs(caplog.records, "definitely-wrong-password")
