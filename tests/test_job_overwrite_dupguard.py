"""Tests for M6.g overwrite & duplicate-job guards.

Covers:
- Duplicate active-job rejection (409 job_already_active) at the API and
  service layer, including the partial unique index enforcement at the DB.
- Fast-path pre-flight subtitle_exists (409) for explicit-language jobs whose
  resolved output file already exists, and the overwrite=True bypass.
- Language-correction rename collision (409 subtitle_exists) and override.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from audio_to_subs.api.services.jobs import create_job_service
from audio_to_subs.core.file_rename import compute_rename_target
from audio_to_subs.db.models import Job, JobSource, JobStatus, OutputFormat

MEDIA_PATH = "/movies/Test Movie (2024)/movie.mkv"


def _settings(same_dir=True):
    return SimpleNamespace(
        SUBTITLES_SAME_DIRECTORY=same_dir,
    )


def _explicit_body():
    return {
        "source": "manual",
        "media_path": MEDIA_PATH,
        "language_mode": "explicit",
        "language_code": "en",
        "output_format": "srt",
    }


# ── API-level duplicate guard ────────────────────────────────────────────────


def test_duplicate_active_job_rejected_409(authenticated_client):
    body = _explicit_body()
    first = authenticated_client.post("/api/jobs", json=body)
    assert first.status_code == 201, first.text

    second = authenticated_client.post("/api/jobs", json=body)
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == "job_already_active"


def test_duplicate_active_job_blocked_even_with_overwrite(authenticated_client):
    body = _explicit_body() | {"overwrite": True}
    first = authenticated_client.post("/api/jobs", json=body)
    assert first.status_code == 201, first.text

    # The duplicate guard is independent of the overwrite flag: two concurrent
    # active jobs for the same (media, language, format) are never allowed.
    second = authenticated_client.post("/api/jobs", json=body)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "job_already_active"


def test_completed_job_frees_slot_for_new_active(authenticated_client, sync_session):
    body = _explicit_body()
    first = authenticated_client.post("/api/jobs", json=body)
    assert first.status_code == 201, first.text
    job_id = first.json()["id"]

    # Mark the first job done; the partial unique index only covers
    # queued/running, so a new active job for the same key is now allowed.
    job = sync_session.get(Job, job_id)
    job.status = JobStatus.DONE
    sync_session.commit()

    second = authenticated_client.post("/api/jobs", json=body)
    assert second.status_code == 201, second.text


# ── Service-level duplicate guard (no HTTP layer) ─────────────────────────────


async def test_create_job_service_duplicate_raises_409(mock_db_session):
    await create_job_service(
        db=mock_db_session,
        settings=_settings(),
        source=JobSource.MANUAL,
        source_ref=None,
        media_path=MEDIA_PATH,
        output_path=None,
        language_code="en",
        output_format=OutputFormat.SRT,
        priority=0,
        language_mode="explicit",
    )
    with pytest.raises(Exception) as exc:
        await create_job_service(
            db=mock_db_session,
            settings=_settings(),
            source=JobSource.MANUAL,
            source_ref=None,
            media_path=MEDIA_PATH,
            output_path=None,
            language_code="en",
            output_format=OutputFormat.SRT,
            priority=0,
            language_mode="explicit",
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "job_already_active"


# ── DB-level partial unique index enforcement ────────────────────────────────


def test_partial_unique_index_blocks_duplicate_active(sync_session, tmp_path):
    """The partial unique index must reject a second active row for the same
    (media_path, language_code, output_format), and must NOT block when the
    first job is no longer active."""
    f = lambda n: Job(  # noqa: E731
        id=f"job-{n}",
        status=JobStatus.QUEUED,
        source=JobSource.MANUAL,
        media_path=MEDIA_PATH,
        language_code="en",
        output_format=OutputFormat.SRT,
    )
    sync_session.add(f(1))
    sync_session.commit()

    sync_session.add(f(2))
    with pytest.raises(IntegrityError):
        sync_session.commit()
    sync_session.rollback()

    # Same key but the first job is done -> allowed.
    done = sync_session.get(Job, "job-1")
    done.status = JobStatus.DONE
    sync_session.commit()

    sync_session.add(f(3))
    sync_session.commit()  # no raise


# ── Pre-flight subtitle_exists (explicit language) ───────────────────────────


async def test_preflight_subtitle_exists_409(mock_db_session, tmp_path):
    media = tmp_path / "movie.mkv"
    media.write_text("data")
    existing = tmp_path / "movie.en.srt"
    existing.write_text("old subtitle")
    settings = _settings(same_dir=True)

    with pytest.raises(Exception) as exc:
        await create_job_service(
            db=mock_db_session,
            settings=settings,
            source=JobSource.MANUAL,
            source_ref=None,
            media_path=str(media),
            output_path=None,
            language_code="en",
            output_format=OutputFormat.SRT,
            priority=0,
            language_mode="explicit",
        )
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert detail["code"] == "subtitle_exists"
    assert detail["existing_path"] == str(existing)
    assert detail["existing_mtime"]


async def test_preflight_subtitle_exists_bypassed_with_overwrite(
    mock_db_session, tmp_path
):
    media = tmp_path / "movie.mkv"
    media.write_text("data")
    (tmp_path / "movie.en.srt").write_text("old subtitle")
    settings = _settings(same_dir=True)

    job = await create_job_service(
        db=mock_db_session,
        settings=settings,
        source=JobSource.MANUAL,
        source_ref=None,
        media_path=str(media),
        output_path=None,
        language_code="en",
        output_format=OutputFormat.SRT,
        priority=0,
        language_mode="explicit",
        overwrite=True,
    )
    assert job.overwrite is True
    assert job.status == JobStatus.QUEUED


async def test_preflight_only_for_explicit_language(mock_db_session, tmp_path):
    """Auto-detect jobs can't be pre-flighted (the final language/path is only
    known after transcription), so an existing file must NOT block creation."""
    media = tmp_path / "movie.mkv"
    media.write_text("data")
    (tmp_path / "movie.und.srt").write_text("old subtitle")
    settings = _settings(same_dir=True)

    job = await create_job_service(
        db=mock_db_session,
        settings=settings,
        source=JobSource.MANUAL,
        source_ref=None,
        media_path=str(media),
        output_path=None,
        language_code=None,
        output_format=OutputFormat.SRT,
        priority=0,
        language_mode="auto",
    )
    assert job.status == JobStatus.QUEUED


# ── Language-correction rename collision ─────────────────────────────────────


def test_language_patch_rename_collision_409(
    authenticated_client, sync_session, tmp_path
):
    src = tmp_path / "movie.und.srt"
    src.write_text("subtitle")
    # Pre-existing target so the rename would clobber it.
    (tmp_path / "movie.fr.srt").write_text("already here")

    job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path=str(tmp_path / "movie.mkv"),
        output_path=str(src),
        language_code="und",
        language_mode="auto",
        needs_language_review=True,
        output_format="srt",
    )
    sync_session.add(job)
    sync_session.commit()

    response = authenticated_client.patch(
        f"/api/jobs/{job.id}/language", json={"language_code": "fr"}
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "subtitle_exists"


def test_language_patch_rename_collision_override(
    authenticated_client, sync_session, tmp_path
):
    src = tmp_path / "movie.und.srt"
    src.write_text("subtitle")
    (tmp_path / "movie.fr.srt").write_text("already here")

    job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path=str(tmp_path / "movie.mkv"),
        output_path=str(src),
        language_code="und",
        language_mode="auto",
        needs_language_review=True,
        output_format="srt",
    )
    sync_session.add(job)
    sync_session.commit()

    response = authenticated_client.patch(
        f"/api/jobs/{job.id}/language",
        json={"language_code": "fr", "overwrite": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["language_code"] == "fr"


def test_compute_rename_target_pure():
    assert compute_rename_target("/m/sub/a.und.srt", "und", "fr") == "/m/sub/a.fr.srt"
    # No clobbering side effect.
    import os

    assert not os.path.exists(compute_rename_target("/nope/x.und.srt", "und", "fr"))
