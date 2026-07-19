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
from audio_to_subs.queue_.events import JOB_PROGRESS_KEY_PREFIX, set_job_progress

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
    authenticated_client.redis_server = server
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


def test_malformed_step_index_does_not_crash(progress_client, sync_session):
    """A corrupted step_index (non-int string) must degrade to None per job,
    not raise or drop the whole overlay (per-job isolation)."""
    job_id = _seed_job(sync_session, JobStatus.RUNNING)
    # Write a deliberately unparseable step_index directly to the shared
    # FakeServer backing the progress_client's redis override.
    server = progress_client.redis_server

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            FakeRedis(server=server).hset(
                f"{JOB_PROGRESS_KEY_PREFIX}{job_id}",
                mapping={
                    "percent": "50",
                    "stage": "x",
                    "message": "m",
                    "step_index": "not-an-int",
                },
            )
        )
    finally:
        loop.close()

    resp = progress_client.get("/api/jobs")
    assert resp.status_code == 200, resp.text
    match = next(j for j in resp.json()["jobs"] if j["id"] == job_id)
    assert match["progress_percent"] == 50
    assert match["progress_step_index"] is None


def test_cancel_running_job_overlays_live_progress(progress_client, sync_session):
    """POST /api/jobs/{id}/cancel on a RUNNING job must reply with the live
    Redis progress overlay, not a hardcoded 0 (regression: the RUNNING branch
    used to return JobResponse.model_validate(job) directly)."""
    job_id = _seed_job(sync_session, JobStatus.RUNNING)
    progress_client.set_progress(
        job_id, percent=37, stage="transcription", message="Transcribing"
    )

    resp = progress_client.post(f"/api/jobs/{job_id}/cancel")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "running"
    assert data["cancel_requested"] is True
    assert data["progress_percent"] == 37
    assert data["progress_stage"] == "transcription"


def test_cancel_done_job_reports_100(progress_client, sync_session):
    """POST /api/jobs/{id}/cancel on a terminal (DONE) job must derive progress
    from status (100), not 0."""
    job_id = _seed_job(sync_session, JobStatus.DONE)

    resp = progress_client.post(f"/api/jobs/{job_id}/cancel")
    assert resp.status_code == 200, resp.text
    assert resp.json()["progress_percent"] == 100


def test_patch_language_done_job_reports_100(progress_client, sync_session):
    """PATCH /api/jobs/{id}/language on a DONE job must derive progress (100),
    not 0 (regression: it returned JobResponse.model_validate(job) directly)."""
    # rename_subtitle_language actually moves the file on disk, so create the
    # source file first (otherwise the rename raises FileNotFoundError).
    src = "/tmp/out.en.srt"
    with open(src, "w") as fh:
        fh.write("")
    job_id = _seed_job(
        sync_session, JobStatus.DONE, output_path=src, language_code="en"
    )

    resp = progress_client.patch(
        f"/api/jobs/{job_id}/language",
        json={"language_code": "fr", "overwrite": True},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["progress_percent"] == 100
    assert data["language_code"] == "fr"
