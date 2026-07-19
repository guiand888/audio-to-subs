"""Tests for the version API endpoint."""

import os
from importlib import metadata

import pytest
from fastapi.testclient import TestClient

from audio_to_subs import _resolve_version
from audio_to_subs.api.app import create_app


@pytest.fixture
def client():
    """Test client without running lifespan (no DB needed for /api/version)."""
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["BEHIND_TLS"] = "false"

    app = create_app()
    app.router.lifespan_context = None
    return TestClient(app, raise_server_exceptions=False)


class TestVersion:
    """Test the /api/version endpoint."""

    def test_version_route_exists_and_is_public(self, client):
        """/api/version returns 200 without authentication."""
        response = client.get("/api/version")
        assert response.status_code == 200

    def test_version_response_structure(self, client):
        """Response has a non-empty string 'version' field."""
        response = client.get("/api/version")
        data = response.json()
        assert "version" in data
        assert isinstance(data["version"], str)
        assert data["version"]

    def test_version_comes_from_package_metadata(self):
        """_resolve_version prefers the version baked into package metadata."""
        # metadata.version("parolesub") is set at install time from the
        # repo-root VERSION file (see setup.py / pyproject.toml).
        expected = metadata.version("parolesub")
        assert _resolve_version() == f"v{expected}" or _resolve_version() == expected

    def test_version_falls_back_to_version_file(self, monkeypatch, tmp_path):
        """When package metadata is unavailable, the VERSION file is used."""
        monkeypatch.setattr(
            metadata,
            "version",
            lambda _name: (_ for _ in ()).throw(metadata.PackageNotFoundError()),
        )
        version_file = tmp_path / "VERSION"
        version_file.write_text("v9.9.9-test\n")

        # __init__.py builds the path via
        # Path(__file__).resolve().parent.parent / "VERSION". Make that whole
        # chain resolve to our temp file.
        class FakePath:
            def __init__(self, *_a):
                pass

            def resolve(self):
                return self

            @property
            def parent(self):
                return self

            def __truediv__(self, _other):
                return self

            def is_file(self):
                return True

            def read_text(self):
                return version_file.read_text()

        monkeypatch.setattr(__import__("audio_to_subs"), "Path", FakePath)
        assert _resolve_version() == "v9.9.9-test"

    def test_missing_version_resolves_to_unknown(self, monkeypatch):
        """With no metadata and no VERSION file, resolution yields 'unknown'."""
        monkeypatch.setattr(
            metadata,
            "version",
            lambda _name: (_ for _ in ()).throw(metadata.PackageNotFoundError()),
        )
        # Simulate a non-existent VERSION file (parent dir has no VERSION).
        fake_file = __import__("pathlib").Path("/nonexistent/VERSION")
        monkeypatch.setattr(
            __import__("audio_to_subs"), "Path", lambda *_a, **_k: fake_file
        )
        assert _resolve_version() == "unknown"
