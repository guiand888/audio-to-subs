"""End-to-end test for M10: startup reconcile of the admin password when the
resolved secret (ADMIN_PASSWORD / ADMIN_PASSWORD_FILE) changes between boots.

Trigger model is "startup reconcile" (decided upfront, not re-litigated
here): on every boot, if the resolved secret differs from the stored admin
hash, the app updates it automatically — no explicit operator action such as
`parolesub admin set-password` is required.

Mirrors the boot-lifecycle style of test_session_secret_bootstrap.py: real
TestClient lifespans, an env-var secret change between boots, and the cached
module-level singletons reset in between so the second boot actually re-reads
the environment (exactly as a real redeploy picking up a rotated Podman
secret / .env var would).
"""

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient


class TestAdminPasswordReconcileAcrossBoots:
    """M10: rotating ADMIN_PASSWORD and rebooting updates the stored admin
    credential, without requiring any explicit operator action."""

    def test_password_rotation_takes_effect_on_next_boot(self, monkeypatch):
        import audio_to_subs.api.settings as api_settings
        import audio_to_subs.auth.sessions as auth_sessions
        import audio_to_subs.db.base as db_base
        from audio_to_subs.api.app import create_app

        # The autouse conftest fixture already builds the schema via
        # Base.metadata.create_all() (not alembic), so it isn't stamped with
        # an alembic_version row. Running the real `alembic upgrade head`
        # subprocess against that DB fails with "table already exists" — the
        # same reason test_session_secret_bootstrap.py mocks it out whenever
        # it exercises the real lifespan via `with TestClient(app):`. Mirror
        # that pattern here; migrations themselves are out of scope for this
        # reconcile behavior.
        migration_ok = patch(
            "subprocess.run",
            return_value=SimpleNamespace(returncode=0, stderr="", stdout=""),
        )

        # password_a matches the admin user the autouse conftest fixture
        # pre-seeds (and the ADMIN_PASSWORD it sets), so boot 1 exercises the
        # "secret unchanged" path — the same path a normal, non-rotating
        # redeploy takes.
        password_a = "test-secure-password-12345"
        password_b = "rotated-secure-password-67890"

        # --- Boot 1: resolved secret already matches the stored hash. Login
        # with the current (A) password succeeds. ---
        app_a = create_app()
        with migration_ok, TestClient(app_a) as client_a:
            response_a = client_a.post(
                "/api/auth/login",
                json={"username": "admin", "password": password_a},
            )
            assert response_a.status_code == 200

        # --- Rotate the secret (simulates the Podman secret / .env
        # ADMIN_PASSWORD being changed before a redeploy), then boot again
        # with a fresh app + fresh lifespan. Reset the cached singletons so
        # the new env var is actually picked up, exactly as a real process
        # restart would. ---
        monkeypatch.setenv("ADMIN_PASSWORD", password_b)
        api_settings._settings = None
        auth_sessions._session_manager = None
        db_base._async_engines.clear()

        app_b = create_app()
        with migration_ok, TestClient(app_b) as client_b:
            # New password now works...
            response_b = client_b.post(
                "/api/auth/login",
                json={"username": "admin", "password": password_b},
            )
            assert response_b.status_code == 200

            # ...and the stale password no longer does.
            response_stale = client_b.post(
                "/api/auth/login",
                json={"username": "admin", "password": password_a},
            )
            assert response_stale.status_code == 401
