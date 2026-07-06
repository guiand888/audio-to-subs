"""Tests for the /api/logs global endpoint."""

from datetime import datetime, timezone
from uuid import uuid4

from audio_to_subs.db.models import Job, JobLog, JobSource, JobStatus, LogLevel


def test_get_global_logs_empty(authenticated_client):
    """GET /api/logs returns empty results on a fresh database."""
    response = authenticated_client.get("/api/logs")

    assert response.status_code == 200
    data = response.json()
    assert data["logs"] == []
    assert data["total"] == 0


def test_get_global_logs_with_entries(authenticated_client, sync_session):
    """GET /api/logs returns all log entries."""
    job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/video.mp4",
    )
    sync_session.add(job)
    sync_session.flush()

    sync_session.add_all(
        [
            JobLog(
                job_id=job.id,
                ts=datetime.now(timezone.utc),
                level=LogLevel.INFO,
                message="Job started",
            ),
            JobLog(
                job_id=job.id,
                ts=datetime.now(timezone.utc),
                level=LogLevel.WARNING,
                message="Low memory",
            ),
            JobLog(
                job_id=None,
                ts=datetime.now(timezone.utc),
                level=LogLevel.ERROR,
                message="Global system error",
            ),
        ]
    )
    sync_session.commit()

    response = authenticated_client.get("/api/logs")
    assert response.status_code == 200
    data = response.json()
    assert len(data["logs"]) == 3
    assert data["total"] == 3


def test_get_global_logs_filter_by_job_id(authenticated_client, sync_session):
    """GET /api/logs can be filtered by job_id."""
    job1 = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/v1.mp4",
    )
    job2 = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/v2.mp4",
    )
    sync_session.add_all([job1, job2])
    sync_session.flush()

    sync_session.add_all(
        [
            JobLog(
                job_id=job1.id,
                ts=datetime.now(timezone.utc),
                level=LogLevel.INFO,
                message="Job 1 log",
            ),
            JobLog(
                job_id=job2.id,
                ts=datetime.now(timezone.utc),
                level=LogLevel.INFO,
                message="Job 2 log",
            ),
        ]
    )
    sync_session.commit()

    response = authenticated_client.get(f"/api/logs?job_id={job1.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["logs"]) == 1
    assert data["logs"][0]["job_id"] == str(job1.id)


def test_get_global_logs_filter_by_level(authenticated_client, sync_session):
    """GET /api/logs can be filtered by log level."""
    sync_session.add_all(
        [
            JobLog(
                job_id=None,
                ts=datetime.now(timezone.utc),
                level=LogLevel.INFO,
                message="Info",
            ),
            JobLog(
                job_id=None,
                ts=datetime.now(timezone.utc),
                level=LogLevel.WARNING,
                message="Warning",
            ),
            JobLog(
                job_id=None,
                ts=datetime.now(timezone.utc),
                level=LogLevel.ERROR,
                message="Error",
            ),
        ]
    )
    sync_session.commit()

    response = authenticated_client.get("/api/logs?level_filter=error")
    assert response.status_code == 200
    data = response.json()
    assert len(data["logs"]) == 1
    assert data["logs"][0]["level"] == "error"


def test_get_global_logs_pagination(authenticated_client, sync_session):
    """GET /api/logs supports limit/offset pagination."""
    sync_session.add_all(
        [
            JobLog(
                job_id=None,
                ts=datetime.now(timezone.utc),
                level=LogLevel.INFO,
                message=f"Log {i}",
            )
            for i in range(10)
        ]
    )
    sync_session.commit()

    resp1 = authenticated_client.get("/api/logs", params={"limit": 3, "offset": 0})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["logs"]) == 3
    assert data1["total"] == 10

    resp2 = authenticated_client.get("/api/logs", params={"limit": 3, "offset": 9})
    assert resp2.status_code == 200
    assert len(resp2.json()["logs"]) == 1
