"""Tests for the Redis live-progress overlay on GET /api/jobs and /api/jobs/{id}.

Phase 2: the DB no longer stores progress columns. In-flight progress lives in
Redis (``job:progress:{id}``); the read paths overlay the snapshot onto
non-terminal jobs so polling sees fresh progress immediately. Terminal jobs
have their progress derived from status (done => 100, otherwise 0). This test
injects a fakeredis instance as the ``get_redis`` dependency.
"""

import asyncio

import pytest
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

from audio_to_subs.api.deps import get_redis
from audio_to_subs.db.models import JobSource, JobStatus
from audio_to_subs.queue_.events import set_job_progress

from .conftest import make_job


@pytest.fixture
def progress_client(authenticated_client):
    """authenticated_client with get_redis overridden by a shared fakeredis.

    A single FakeServer backs every client so snapshots seeded by a test
    (in one event loop) are visible to the app's per-request client (which
    runs in the TestClient's own event loop).
    """
    server = FakeServer()

    def _override():
        return FakeRedis(server=server)

    authenticated_client.app.dependency_overrides[get_redis] = _override

    def _set(job_id, **fields):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                set_job_progress(FakeRedis(server=server), job_id, **fields)
            )
        finally:
            loop.close()

    authenticated_client.set_progress = _set
    yield authenticated_client
    authenticated_client.app.dependency_overrides.pop(get_redis, None)


def _seed_job(sync_session, status, **kwargs):
    job = make_job(status=status, source=JobSource.MANUAL, **kwargs)
    sync_session.add(job)
    sync_session.commit()
    return str(job.id)


def test_running_job_overlays_redis_progress(progress_client, sync_session):
    """A running job's GET /api/jobs must reflect the Redis snapshot."""
    job_id = _seed_job(sync_session, JobStatus.RUNNING)
    progress_client.set_progress(
        job_id,
        percent=42,
        stage="transcription",
        message="Transcribing",
        step_index=2,
        step_total=5,
    )

    resp = progress_client.get("/api/jobs")
    assert resp.status_code == 200, resp.text
    jobs = resp.json()["jobs"]
    match = next(j for j in jobs if j["id"] == job_id)
    assert match["progress_percent"] == 42
    assert match["progress_stage"] == "transcription"
    assert match["progress_message"] == "Transcribing"
    assert match["progress_step_index"] == 2
    assert match["progress_step_total"] == 5


def test_missing_redis_snapshot_falls_back_to_zero(progress_client, sync_session):
    """A running job with no Redis snapshot reports 0 (no DB column to fall back to)."""
    job_id = _seed_job(sync_session, JobStatus.RUNNING)

    resp = progress_client.get("/api/jobs")
    assert resp.status_code == 200, resp.text
    match = next(j for j in resp.json()["jobs"] if j["id"] == job_id)
    assert match["progress_percent"] == 0
    assert match["progress_stage"] is None
    assert match["progress_message"] is None


def test_terminal_job_progress_derived_from_status(progress_client, sync_session):
    """A done job reports 100; a failed/cancelled job reports 0. Any lingering
    Redis snapshot must NOT override the terminal derivation (overlay only
    targets non-terminal jobs, and a terminal job's key should be cleared)."""
    done_id = _seed_job(sync_session, JobStatus.DONE)
    failed_id = _seed_job(sync_session, JobStatus.FAILED)
    cancelled_id = _seed_job(sync_session, JobStatus.CANCELLED)

    # Even if stale snapshots linger, terminal jobs must derive from status.
    progress_client.set_progress(done_id, percent=13, stage="extract", message="x")
    progress_client.set_progress(failed_id, percent=55, stage="extract", message="x")
    progress_client.set_progress(cancelled_id, percent=77, stage="extract", message="x")

    resp = progress_client.get("/api/jobs")
    assert resp.status_code == 200, resp.text
    by_id = {j["id"]: j for j in resp.json()["jobs"]}
    assert by_id[done_id]["progress_percent"] == 100
    assert by_id[failed_id]["progress_percent"] == 0
    assert by_id[cancelled_id]["progress_percent"] == 0


def test_get_single_job_overlays_redis(progress_client, sync_session):
    """GET /api/jobs/{id} overlays the same way as the list endpoint."""
    job_id = _seed_job(sync_session, JobStatus.RUNNING)
    progress_client.set_progress(job_id, percent=88, stage="formatting", message="formatting")

    resp = progress_client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["progress_percent"] == 88
    assert data["progress_stage"] == "formatting"
