"""Tests for the /api/history endpoint."""

import pytest
from uuid import uuid4

from audio_to_subs.db.models import Job, JobStatus, JobSource


def test_get_history_empty(api_client):
    """GET /api/history returns empty results on a fresh database."""
    response = api_client.get("/api/history")

    assert response.status_code == 200
    data = response.json()
    assert data["jobs"] == []
    assert data["stats"]["total_jobs"] == 0
    assert data["stats"]["total_cost_usd"] == 0
    assert data["stats"]["total_duration_seconds"] == 0


def test_get_history_with_done_jobs(client, sync_session):
    """GET /api/history returns done jobs with aggregated stats."""
    job1 = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/video1.mp4",
        audio_duration_seconds=120.5,
        estimated_cost_usd=0.50,
        language_code="en",
    )
    job2 = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.BAZARR_MOVIE,
        source_ref="123",
        media_path="/test/video2.mp4",
        audio_duration_seconds=180.0,
        estimated_cost_usd=0.75,
        language_code="fr",
    )
    sync_session.add_all([job1, job2])
    sync_session.commit()

    response = client.get("/api/history")
    assert response.status_code == 200
    data = response.json()

    assert len(data["jobs"]) == 2
    assert data["stats"]["total_jobs"] == 2
    assert data["stats"]["total_cost_usd"] == pytest.approx(1.25, abs=0.001)
    assert data["stats"]["total_duration_seconds"] == pytest.approx(300.5, abs=0.01)
    assert data["stats"]["average_cost_usd"] == pytest.approx(0.625, abs=0.001)
    assert data["stats"]["count_by_status"]["done"] == 2
    assert data["stats"]["count_by_language"]["en"] == 1
    assert data["stats"]["count_by_language"]["fr"] == 1


def test_get_history_filters_by_status(client, sync_session):
    """GET /api/history can be filtered by status."""
    sync_session.add_all([
        Job(id=str(uuid4()), status=JobStatus.DONE, source=JobSource.MANUAL, media_path="/test/v1.mp4"),
        Job(id=str(uuid4()), status=JobStatus.FAILED, source=JobSource.MANUAL, media_path="/test/v2.mp4"),
        Job(id=str(uuid4()), status=JobStatus.CANCELLED, source=JobSource.MANUAL, media_path="/test/v3.mp4"),
    ])
    sync_session.commit()

    response = client.get("/api/history", params={"status_filter": ["done"]})
    assert response.status_code == 200
    data = response.json()
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["status"] == "done"

    response = client.get("/api/history", params={"status_filter": ["done", "failed"]})
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 2


def test_get_history_filters_by_source(client, sync_session):
    """GET /api/history can be filtered by source."""
    sync_session.add_all([
        Job(id=str(uuid4()), status=JobStatus.DONE, source=JobSource.BAZARR_MOVIE, source_ref="123", media_path="/test/v1.mp4"),
        Job(id=str(uuid4()), status=JobStatus.DONE, source=JobSource.MANUAL, media_path="/test/v2.mp4"),
    ])
    sync_session.commit()

    response = client.get("/api/history", params={"source_filter": "bazarr_movie"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["source"] == "bazarr_movie"


def test_get_history_pagination(client, sync_session):
    """GET /api/history supports limit/offset pagination."""
    sync_session.add_all([
        Job(id=str(uuid4()), status=JobStatus.DONE, source=JobSource.MANUAL, media_path=f"/test/v{i}.mp4")
        for i in range(5)
    ])
    sync_session.commit()

    resp1 = client.get("/api/history", params={"limit": 2, "offset": 0})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["jobs"]) == 2
    assert data1["total"] == 5

    resp2 = client.get("/api/history", params={"limit": 2, "offset": 4})
    assert resp2.status_code == 200
    assert len(resp2.json()["jobs"]) == 1


def test_get_history_excludes_queued_and_running(client, sync_session):
    """GET /api/history excludes QUEUED and RUNNING jobs."""
    sync_session.add_all([
        Job(id=str(uuid4()), status=JobStatus.QUEUED, source=JobSource.MANUAL, media_path="/test/v1.mp4"),
        Job(id=str(uuid4()), status=JobStatus.RUNNING, source=JobSource.MANUAL, media_path="/test/v2.mp4"),
        Job(id=str(uuid4()), status=JobStatus.DONE, source=JobSource.MANUAL, media_path="/test/v3.mp4"),
    ])
    sync_session.commit()

    response = client.get("/api/history")
    assert response.status_code == 200
    data = response.json()

    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["status"] == "done"
