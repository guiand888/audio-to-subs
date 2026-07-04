"""Tests for job reaper (stale job cleanup)."""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select

from audio_to_subs.db.models import Job, JobStatus, JobSource
from audio_to_subs.queue_.reaper import delete_stale_jobs


@pytest.mark.asyncio
async def test_reaper_only_deletes_old_jobs(mock_db_session):
    """Reaper should only delete jobs older than stale_threshold."""
    now = datetime.now(timezone.utc)
    stale_threshold = timedelta(hours=24)

    # Add a fresh job (should NOT be deleted)
    fresh_job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/fresh.mp4",
        output_format="srt",
        updated_at=now,
    )

    # Add an old job (should be deleted)
    old_job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/old.mp4",
        output_format="srt",
        updated_at=now - timedelta(days=2),
    )

    mock_db_session.add_all([fresh_job, old_job])
    await mock_db_session.flush()

    # Run reaper
    deleted_count = await delete_stale_jobs(mock_db_session, stale_threshold)

    # Verify exactly one job was deleted
    assert deleted_count == 1

    # Verify fresh job still exists
    result = await mock_db_session.execute(
        select(Job).where(Job.id == fresh_job.id)
    )
    assert result.scalar_one_or_none() is not None

    # Verify old job is gone
    result = await mock_db_session.execute(
        select(Job).where(Job.id == old_job.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_reaper_ignores_active_jobs(mock_db_session):
    """Reaper should not delete jobs with active status, regardless of age."""
    now = datetime.now(timezone.utc)
    stale_threshold = timedelta(hours=24)

    # Add an old QUEUED job (still active)
    active_job = Job(
        id=str(uuid4()),
        status=JobStatus.QUEUED,
        source=JobSource.MANUAL,
        media_path="/test/active.mp4",
        output_format="srt",
        updated_at=now - timedelta(days=2),
    )

    # Add an old DONE job (inactive)
    stale_job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/stale.mp4",
        output_format="srt",
        updated_at=now - timedelta(days=2),
    )

    mock_db_session.add_all([active_job, stale_job])
    await mock_db_session.flush()

    # Run reaper
    deleted_count = await delete_stale_jobs(mock_db_session, stale_threshold)

    # Only the DONE job should be deleted
    assert deleted_count == 1

    # Verify active job still exists
    result = await mock_db_session.execute(
        select(Job).where(Job.id == active_job.id)
    )
    assert result.scalar_one_or_none() is not None

    # Verify stale job is gone
    result = await mock_db_session.execute(
        select(Job).where(Job.id == stale_job.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_reaper_timestamp_consistency(mock_db_session):
    """Test that timestamp format in DB is consistent with comparison logic."""
    now = datetime.now(timezone.utc)
    stale_threshold = timedelta(minutes=1)

    # Job just updated (very recent)
    fresh = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/fresh.mp4",
        output_format="srt",
        updated_at=now - timedelta(seconds=10),
    )

    # Job updated 2 minutes ago (should be stale)
    stale = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/stale.mp4",
        output_format="srt",
        updated_at=now - timedelta(minutes=2),
    )

    mock_db_session.add_all([fresh, stale])
    await mock_db_session.flush()

    # Run reaper with 1-minute threshold
    deleted_count = await delete_stale_jobs(mock_db_session, stale_threshold)

    # Exactly one should be deleted
    assert deleted_count == 1

    # Verify fresh job still exists
    result = await mock_db_session.execute(
        select(Job).where(Job.id == fresh.id)
    )
    assert result.scalar_one_or_none() is not None

    # Verify stale job is gone
    result = await mock_db_session.execute(
        select(Job).where(Job.id == stale.id)
    )
    assert result.scalar_one_or_none() is None
