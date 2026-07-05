"""Tests for the /api/jobs/{id}/notify-bazarr endpoint."""

from uuid import uuid4

import pytest

from audio_to_subs.db.models import Job, JobSource, JobStatus


def test_notify_bazarr_job_not_found(api_client):
    """POST /api/jobs/{id}/notify-bazarr returns 404 for a non-existent job."""
    fake_id = uuid4()
    response = api_client.post(f"/api/jobs/{fake_id}/notify-bazarr")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_notify_bazarr_manual_job(api_client, sync_session):
    """POST /api/jobs/{id}/notify-bazarr skips manual jobs."""
    job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/video.mp4",
    )
    sync_session.add(job)
    sync_session.commit()

    response = client.post(f"/api/jobs/{job.id}/notify-bazarr")
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "skipped"
    assert "Manual job" in data["reason"]


def test_notify_bazarr_bazarr_movie_no_bazarr_config(api_client, sync_session):
    """POST /api/jobs/{id}/notify-bazarr skips when Bazarr is not configured."""
    job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.BAZARR_MOVIE,
        source_ref="123",
        media_path="/test/video.mp4",
    )
    sync_session.add(job)
    sync_session.commit()

    response = client.post(f"/api/jobs/{job.id}/notify-bazarr")
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "skipped"
    assert "Bazarr not configured" in data["reason"]
