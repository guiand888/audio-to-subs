"""BDD steps for login_race_condition.feature.

Covers:
- First-boot session secret generation
- Login success/failure flows
- Protected route access with/without session
- Session secret rotation invalidating old cookies
- Healthz readiness

Uses the shared conftest fixtures (api_client, authenticated_client, sync_session)
which already set up a per-test SQLite DB, seed an admin user, and configure
the session secret via env vars.
"""

import pytest
from pytest_bdd import given, parsers, scenario, then, when

# ---------------------------------------------------------------------------
# Scenario decorators
# ---------------------------------------------------------------------------


@scenario(
    "../login_race_condition.feature", "First boot generates the session secret file"
)
def test_first_boot_generates_session_secret():
    """First-boot: _ensure_session_secret_file() creates the file."""


@scenario(
    "../login_race_condition.feature", "Login with valid credentials on a ready backend"
)
def test_login_valid_credentials():
    """Valid login returns 200 + session cookie."""


@scenario("../login_race_condition.feature", "Login with wrong password returns 401")
def test_login_wrong_password():
    """Wrong password returns 401."""


@scenario("../login_race_condition.feature", "Login with unknown user returns 401")
def test_login_unknown_user():
    """Unknown user returns 401 (timing-safe)."""


@scenario(
    "../login_race_condition.feature",
    "Access a protected route without a session cookie",
)
def test_protected_route_without_session():
    """Unauthenticated request to a protected route returns 401."""


@scenario(
    "../login_race_condition.feature",
    "Access a protected route with a valid session cookie",
)
def test_protected_route_with_session():
    """Authenticated request to a protected route returns 200."""


@scenario(
    "../login_race_condition.feature",
    "Session cookie is validated against the signing secret",
)
def test_session_secret_rotation_invalidates_cookie():
    """Rotating the secret invalidates old cookies (401 + cookie cleared)."""


@scenario(
    "../login_race_condition.feature",
    "Healthz returns 200 when the database is reachable",
)
def test_healthz_ok():
    """Healthz returns 200 when DB is up."""


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------


@pytest.fixture
def context():
    """Shared state for BDD scenarios."""

    class Context:
        def __init__(self):
            self.response = None
            self.session_cookie = None
            self.secret_file_path = None

    return Context()


# ---------------------------------------------------------------------------
# Background steps
# ---------------------------------------------------------------------------


@given("the application database is initialized")
def database_initialized(api_client):
    """The api_client fixture already creates and migrates the DB."""
    assert api_client is not None


@given("the session secret file exists")
def session_secret_exists():
    """The conftest sets SESSION_SECRET directly, so no file is needed."""
    pass


@given(parsers.parse('an admin user "{username}" with password "{password}" exists'))
def admin_user_exists(username, password):
    """The conftest pre-seeds an admin user with known credentials."""
    assert username == "admin"
    assert password == "test-secure-password-12345"


# ---------------------------------------------------------------------------
# First-boot scenario
# ---------------------------------------------------------------------------


@given("the session secret file does not exist")
def secret_file_missing(context, tmp_path, monkeypatch):
    """Point SESSION_SECRET_FILE at a path that does not exist yet."""
    import audio_to_subs.api.settings as api_settings
    import audio_to_subs.auth.sessions as auth_sessions

    api_settings._settings = None
    auth_sessions._session_manager = None

    secret_file = tmp_path / "session_secret"
    context.secret_file_path = str(secret_file)

    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("SESSION_SECRET_FILE", str(secret_file))

    assert not secret_file.exists()


@given("no SESSION_SECRET environment variable is set")
def no_session_secret_env(monkeypatch):
    """Ensure SESSION_SECRET is not in the environment."""
    monkeypatch.delenv("SESSION_SECRET", raising=False)


@given("SESSION_SECRET_FILE points to the missing file")
def secret_file_points_to_missing(context):
    """Already set by the 'does not exist' step."""
    assert context.secret_file_path is not None


@when("the application is created")
def create_application(context):
    """Call create_app() which triggers _ensure_session_secret_file()."""
    import audio_to_subs.api.app as app_module

    context.app = app_module.create_app()


@then("the session secret file should be generated")
def secret_file_generated(context):
    from pathlib import Path

    assert Path(context.secret_file_path).exists()


@then("the session secret file should not contain the placeholder value")
def secret_file_not_placeholder(context):
    from pathlib import Path

    content = Path(context.secret_file_path).read_text().strip()
    assert content != "changeme"
    assert len(content) > 0


# ---------------------------------------------------------------------------
# Login steps
# ---------------------------------------------------------------------------


@when(parsers.parse('I log in with username "{username}" and password "{password}"'))
def login(context, api_client, username, password):
    """POST /api/auth/login with given credentials."""
    context.response = api_client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    context.session_cookie = context.response.cookies.get("ats_session")


# ---------------------------------------------------------------------------
# Protected route steps
# ---------------------------------------------------------------------------


@when("I request the jobs list without authentication")
def request_jobs_unauthenticated(context, api_client):
    """GET /api/jobs without a session cookie."""
    context.response = api_client.get("/api/jobs")


@given('I am logged in as "admin"')
def logged_in(context, api_client):
    """Log in and capture the session cookie."""
    response = api_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-secure-password-12345"},
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    context.session_cookie = response.cookies.get("ats_session")
    assert context.session_cookie is not None


@when("I request the jobs list with the session cookie")
def request_jobs_authenticated(context, api_client):
    """GET /api/jobs with the session cookie."""
    context.response = api_client.get(
        "/api/jobs",
        cookies={"ats_session": context.session_cookie},
    )


# ---------------------------------------------------------------------------
# Session secret rotation scenario
# ---------------------------------------------------------------------------


@given("the session secret has been rotated")
def rotate_session_secret(monkeypatch):
    """Reset the session manager with a new secret so old tokens are invalid."""
    import audio_to_subs.api.settings as api_settings
    import audio_to_subs.auth.sessions as auth_sessions

    api_settings._settings = None
    auth_sessions._session_manager = None
    monkeypatch.setenv("SESSION_SECRET", "new-rotated-secret-xyz")


@when("I request the jobs list with the old session cookie")
def request_jobs_with_stale_cookie(context, api_client):
    """GET /api/jobs with a cookie signed by the old secret."""
    context.response = api_client.get(
        "/api/jobs",
        cookies={"ats_session": context.session_cookie},
    )


@then("the session cookie should be cleared")
def session_cookie_cleared(context):
    """The response should delete/invalidate the session cookie."""
    cookie = context.response.cookies.get("ats_session")
    assert cookie in (None, "")


# ---------------------------------------------------------------------------
# Healthz steps
# ---------------------------------------------------------------------------


@when("I check the health endpoint")
def check_health(context, api_client):
    """GET /api/healthz."""
    context.response = api_client.get("/api/healthz")


@then(parsers.parse('the response should contain database status "{expected}"'))
def healthz_database_status(context, expected):
    data = context.response.json()
    assert data["database"] == expected


# ---------------------------------------------------------------------------
# Generic assertions
# ---------------------------------------------------------------------------


@then(parsers.parse("the response status should be {status_code:d}"))
def response_status(context, status_code):
    assert context.response.status_code == status_code, (
        f"Expected {status_code}, got {context.response.status_code}: "
        f"{context.response.text}"
    )


@then("the response should contain a session cookie")
def response_has_session_cookie(context):
    assert context.session_cookie is not None
    assert len(context.session_cookie) > 0


@then(parsers.parse('the response should contain the username "{username}"'))
def response_contains_username(context, username):
    data = context.response.json()
    assert data["user"]["username"] == username


@then(parsers.parse('the response should contain "{text}"'))
def response_contains_text(context, text):
    body = context.response.text
    assert text in body, f"'{text}' not found in response: {body}"
