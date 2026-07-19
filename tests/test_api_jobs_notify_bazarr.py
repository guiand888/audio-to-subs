"""Tests for the /api/jobs/{id}/notify-bazarr endpoint."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import select

from audio_to_subs.db.models import Job, JobLog, JobSource, JobStatus, LogLevel


def test_notify_bazarr_job_not_found(authenticated_client):
    """POST /api/jobs/{id}/notify-bazarr returns 404 for a non-existent job."""
    fake_id = uuid4()
    response = authenticated_client.post(f"/api/jobs/{fake_id}/notify-bazarr")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_notify_bazarr_manual_job(authenticated_client, sync_session):
    """POST /api/jobs/{id}/notify-bazarr skips manual jobs."""
    job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/video.mp4",
    )
    sync_session.add(job)
    sync_session.commit()

    response = authenticated_client.post(f"/api/jobs/{job.id}/notify-bazarr")
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "skipped"
    assert "Manual job" in data["reason"]


def test_notify_bazarr_bazarr_movie_no_bazarr_config(
    authenticated_client, sync_session
):
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

    response = authenticated_client.post(f"/api/jobs/{job.id}/notify-bazarr")
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "skipped"
    assert "Bazarr not configured" in data["reason"]


def test_notify_bazarr_movie_success_writes_info_job_log(
    authenticated_client, sync_session
):
    """A successful rescan trigger persists an INFO job_log entry, so the
    UI's activity log reflects the outcome, not just the HTTP response."""
    job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.BAZARR_MOVIE,
        source_ref="123",
        media_path="/test/video.mp4",
    )
    sync_session.add(job)
    sync_session.commit()

    mock_client = AsyncMock()
    mock_client.rescan_movie = AsyncMock(return_value=True)
    mock_client.close = AsyncMock()

    with patch(
        "audio_to_subs.bazarr.poller.get_bazarr_client_with_settings",
        new=AsyncMock(return_value=(mock_client, "http://bazarr", "key", 30.0)),
    ):
        response = authenticated_client.post(f"/api/jobs/{job.id}/notify-bazarr")

    assert response.status_code == 202
    assert response.json()["status"] == "triggered"

    log = sync_session.execute(
        select(JobLog).where(JobLog.job_id == job.id)
    ).scalar_one()
    assert log.level == LogLevel.INFO
    assert "rescan" in log.message.lower()


def test_notify_bazarr_movie_failure_writes_warning_job_log(
    authenticated_client, sync_session
):
    """A failed rescan trigger persists a WARNING job_log entry."""
    job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.BAZARR_MOVIE,
        source_ref="123",
        media_path="/test/video.mp4",
    )
    sync_session.add(job)
    sync_session.commit()

    mock_client = AsyncMock()
    mock_client.rescan_movie = AsyncMock(side_effect=RuntimeError("boom"))
    mock_client.close = AsyncMock()

    with patch(
        "audio_to_subs.bazarr.poller.get_bazarr_client_with_settings",
        new=AsyncMock(return_value=(mock_client, "http://bazarr", "key", 30.0)),
    ):
        response = authenticated_client.post(f"/api/jobs/{job.id}/notify-bazarr")

    assert response.status_code == 202
    assert response.json()["status"] == "failed"

    log = sync_session.execute(
        select(JobLog).where(JobLog.job_id == job.id)
    ).scalar_one()
    assert log.level == LogLevel.WARNING
