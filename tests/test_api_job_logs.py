"""Tests for the /api/jobs/{id}/logs endpoints."""

from uuid import uuid4

from audio_to_subs.db.models import Job, JobLog, JobSource, JobStatus, LogLevel


def _make_job(sync_session, **overrides) -> Job:
    defaults = dict(
        id=str(uuid4()),
        status=JobStatus.RUNNING,
        source=JobSource.MANUAL,
        media_path="/test/video.mp4",
        output_format="srt",
    )
    defaults.update(overrides)
    job = Job(**defaults)
    sync_session.add(job)
    sync_session.commit()
    return job


class TestCreateJobLog:
    """Test POST /api/jobs/{id}/logs."""

    def test_create_job_log_persists_entry(self, authenticated_client, sync_session):
        """Regression: job_id (a UUID path param) must be stored as str,
        since JobLog.job_id is a String(36) column. Passing the UUID object
        directly raises a binding error at the SQLite driver level.
        """
        job = _make_job(sync_session)

        response = authenticated_client.post(
            f"/api/jobs/{job.id}/logs",
            params={"level": "info", "message": "hello from test"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["message"] == "hello from test"
        assert data["job_id"] == str(job.id)

    def test_create_job_log_unknown_job_returns_404(self, authenticated_client):
        response = authenticated_client.post(
            f"/api/jobs/{uuid4()}/logs",
            params={"message": "should not be created"},
        )
        assert response.status_code == 404


class TestGetJobLogs:
    """Test GET /api/jobs/{id}/logs."""

    def test_get_job_logs_returns_entries(self, authenticated_client, sync_session):
        job = _make_job(sync_session)
        sync_session.add(
            JobLog(
                job_id=job.id,
                level=LogLevel.INFO,
                message="existing log",
            )
        )
        sync_session.commit()

        response = authenticated_client.get(f"/api/jobs/{job.id}/logs")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["logs"][0]["message"] == "existing log"

    def test_get_job_logs_unknown_job_returns_404(self, authenticated_client):
        response = authenticated_client.get(f"/api/jobs/{uuid4()}/logs")
        assert response.status_code == 404
