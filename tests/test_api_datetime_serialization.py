"""Tests that API datetime fields carry an explicit UTC offset on the wire.

The DB stores naive UTC timestamps (SQLite CURRENT_TIMESTAMP). Without an
offset, Pydantic v2 serializes naive datetimes bare (e.g.
"2024-01-01T12:00:00"), which JavaScript's Date parser misreads as local
time — the root cause of the "UI always shows UTC" symptom. Every response
datetime must be emitted with an explicit offset so the frontend can convert
correctly to the user's chosen timezone.
"""

from datetime import datetime, timezone
from uuid import uuid4

from audio_to_subs.db.models import Job, JobLog, JobSource, JobStatus, LogLevel


def _has_utc_offset(ts: str) -> bool:
    """True when an ISO timestamp carries an explicit UTC offset designator.

    Pydantic v2 serializes timezone.utc-aware datetimes with a trailing 'Z';
    bare naive datetimes have no offset. Accept both 'Z' and '+00:00' forms.
    """
    return ts.endswith("Z") or ts.endswith("+00:00")


def test_job_response_datetimes_have_utc_offset(authenticated_client, sync_session):
    """GET /api/jobs emits created_at/updated_at with a UTC offset."""
    sync_session.add(
        Job(
            id=str(uuid4()),
            status=JobStatus.DONE,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
        )
    )
    sync_session.commit()

    response = authenticated_client.get("/api/jobs")
    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert len(jobs) == 1
    for field in ("created_at", "updated_at"):
        ts = jobs[0][field]
        assert _has_utc_offset(ts), f"{field}={ts} missing UTC offset"


def test_job_detail_datetimes_have_utc_offset(authenticated_client, sync_session):
    """GET /api/jobs/{id} emits datetime fields with a UTC offset."""
    job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/video.mp4",
        started_at=datetime(2024, 1, 1, 10, 0, 0),
        finished_at=datetime(2024, 1, 1, 10, 5, 0),
    )
    sync_session.add(job)
    sync_session.commit()

    response = authenticated_client.get(f"/api/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()
    for field in ("created_at", "started_at", "finished_at", "updated_at"):
        ts = data[field]
        assert _has_utc_offset(ts), f"{field}={ts} missing UTC offset"


def test_log_response_ts_has_utc_offset(authenticated_client, sync_session):
    """GET /api/logs emits ts with a UTC offset."""
    sync_session.add(
        JobLog(
            job_id=None,
            ts=datetime.now(timezone.utc),
            level=LogLevel.INFO,
            message="tz-offset-test-marker",
        )
    )
    sync_session.commit()

    response = authenticated_client.get("/api/logs")
    assert response.status_code == 200
    logs = response.json()["logs"]
    ours = [log for log in logs if log["message"] == "tz-offset-test-marker"]
    assert len(ours) == 1
    assert _has_utc_offset(ours[0]["ts"]), f"ts={ours[0]['ts']} missing UTC offset"


def test_utc_aware_model_stamps_naive_datetimes():
    """Unit: UTCAwareModel stamps naive datetime fields with UTC tzinfo."""
    from audio_to_subs.api.routes._helpers import UTCAwareModel

    class Demo(UTCAwareModel):
        model_config = {"from_attributes": True}
        ts: datetime
        maybe: datetime | None = None

    # naive datetime in -> UTC-aware datetime out
    demo = Demo(ts=datetime(2024, 1, 1, 12, 0, 0))
    assert demo.ts.tzinfo is not None
    assert demo.ts.utcoffset().total_seconds() == 0
    serialized = demo.model_dump(mode="json")
    assert _has_utc_offset(serialized["ts"])

    # aware datetime is left untouched (not double-stamped)
    aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    demo2 = Demo(ts=aware)
    assert demo2.ts is aware

    # None stays None
    demo3 = Demo(ts=datetime(2024, 1, 1, 12, 0, 0), maybe=None)
    assert demo3.maybe is None
