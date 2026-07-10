"""Tests for the shared write_job_log helper."""

from uuid import uuid4

from sqlalchemy import select

from audio_to_subs.db.job_logs import write_job_log
from audio_to_subs.db.models import Job, JobLog, JobSource, JobStatus, LogLevel


async def test_write_job_log_global_entry(mock_db_session, sync_session):
    """job_id=None writes a global entry (job_id column stored as NULL, not
    the literal string "None")."""
    await write_job_log(mock_db_session, LogLevel.INFO, "global message")

    row = sync_session.execute(select(JobLog)).scalar_one()
    assert row.job_id is None
    assert row.level == LogLevel.INFO
    assert row.message == "global message"


async def test_write_job_log_job_scoped_entry(mock_db_session, sync_session):
    job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/video.mp4",
    )
    sync_session.add(job)
    sync_session.commit()

    await write_job_log(mock_db_session, LogLevel.ERROR, "job failed", job_id=job.id)

    row = sync_session.execute(select(JobLog)).scalar_one()
    assert row.job_id == str(job.id)
    assert row.level == LogLevel.ERROR
    assert row.message == "job failed"


async def test_write_job_log_accepts_uuid_job_id(mock_db_session, sync_session):
    """job_id may be a UUID object, not just a str."""
    job_uuid = uuid4()
    job = Job(
        id=str(job_uuid),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/video.mp4",
    )
    sync_session.add(job)
    sync_session.commit()

    await write_job_log(mock_db_session, LogLevel.INFO, "ok", job_id=job_uuid)

    row = sync_session.execute(select(JobLog)).scalar_one()
    assert row.job_id == str(job_uuid)
