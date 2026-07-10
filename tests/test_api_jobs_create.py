"""Tests for POST /api/jobs - language_mode handling in create_job_service.

Covers the auto-mode language_code override and the output-path ordering
fix (the default-language setting must be applied before the output path
is generated, not after).

media_path is a plain string under /movies (the app's default
MOVIES_ROOT_PATH) rather than a real file - path validation and output-path
generation are pure string operations that don't require the file to exist.
"""

import json

from sqlalchemy import select

from audio_to_subs.db.models import Job, JobLog, LogLevel, Setting

MEDIA_PATH = "/movies/Test Movie (2024)/movie.mkv"


def test_create_job_auto_mode_ignores_language_code(authenticated_client):
    """language_mode='auto' must force language_code to None server-side,
    even if the client sends one."""
    response = authenticated_client.post(
        "/api/jobs",
        json={
            "source": "manual",
            "media_path": MEDIA_PATH,
            "language_mode": "auto",
            "language_code": "en",
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["language_mode"] == "auto"
    assert data["language_code"] is None
    # No language suffix yet - the real language isn't known until the
    # worker finishes transcribing.
    assert data["output_path"] == "/movies/Test Movie (2024)/movie.srt"


def test_create_job_writes_info_job_log(authenticated_client, sync_session):
    """Job creation persists an INFO job_log entry visible in the UI's
    activity log, not just an HTTP response."""
    response = authenticated_client.post(
        "/api/jobs",
        json={
            "source": "manual",
            "media_path": MEDIA_PATH,
            "language_mode": "auto",
        },
    )
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]

    log = sync_session.execute(
        select(JobLog).where(JobLog.job_id == job_id)
    ).scalar_one()
    assert log.level == LogLevel.INFO
    assert "Job created" in log.message


def test_create_job_explicit_mode_keeps_language_code(authenticated_client):
    response = authenticated_client.post(
        "/api/jobs",
        json={
            "source": "manual",
            "media_path": MEDIA_PATH,
            "language_mode": "explicit",
            "language_code": "fr",
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["language_mode"] == "explicit"
    assert data["language_code"] == "fr"
    assert data["output_path"] == "/movies/Test Movie (2024)/movie.fr.srt"


def test_create_job_auto_mode_does_not_apply_default_language(
    authenticated_client, sync_session
):
    """Auto mode must never fall back to the default_language setting -
    that would defeat the point of letting Mistral auto-detect."""
    sync_session.add(Setting(key="default_language", value_json=json.dumps("es")))
    sync_session.commit()

    response = authenticated_client.post(
        "/api/jobs",
        json={
            "source": "manual",
            "media_path": MEDIA_PATH,
            "language_mode": "auto",
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["language_code"] is None
    assert data["output_path"] == "/movies/Test Movie (2024)/movie.srt"


def test_create_job_explicit_mode_no_code_applies_default_language_to_path(
    authenticated_client, sync_session
):
    """Regression test for a pre-existing ordering bug: the output path used
    to be generated from the raw (un-defaulted) language_code, so a job
    relying on the default-language setting got a path with no language
    suffix even though the persisted DB row had one. The path must reflect
    the *final*, defaulted language code."""
    sync_session.add(Setting(key="default_language", value_json=json.dumps("es")))
    sync_session.commit()

    response = authenticated_client.post(
        "/api/jobs",
        json={
            "source": "manual",
            "media_path": MEDIA_PATH,
            "language_mode": "explicit",
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["language_code"] == "es"
    assert data["output_path"] == "/movies/Test Movie (2024)/movie.es.srt"

    sync_session.expire_all()
    job = sync_session.get(Job, data["id"])
    assert job.language_code == "es"
    assert job.output_path == "/movies/Test Movie (2024)/movie.es.srt"
