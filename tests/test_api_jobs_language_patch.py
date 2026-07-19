"""Tests for the PATCH /api/jobs/{id}/language endpoint."""

from uuid import uuid4

from audio_to_subs.db.models import Job, JobSource, JobStatus


def _make_job(sync_session, tmp_path, **overrides):
    output_path = tmp_path / "movie.und.srt"
    output_path.write_text("subtitle content")
    defaults = {
        "id": str(uuid4()),
        "status": JobStatus.DONE,
        "source": JobSource.MANUAL,
        "media_path": str(tmp_path / "movie.mkv"),
        "output_path": str(output_path),
        "language_code": "und",
        "language_mode": "auto",
        "needs_language_review": True,
        "output_format": "srt",
    }
    defaults.update(overrides)
    job = Job(**defaults)
    sync_session.add(job)
    sync_session.commit()
    return job


def test_patch_language_job_not_found(authenticated_client):
    fake_id = uuid4()
    response = authenticated_client.patch(
        f"/api/jobs/{fake_id}/language", json={"language_code": "fr"}
    )
    assert response.status_code == 404


def test_patch_language_rejects_non_done_job(
    authenticated_client, sync_session, tmp_path
):
    job = _make_job(sync_session, tmp_path, status=JobStatus.RUNNING)

    response = authenticated_client.patch(
        f"/api/jobs/{job.id}/language", json={"language_code": "fr"}
    )

    assert response.status_code == 400
    assert "completed" in response.json()["detail"].lower()


def test_patch_language_rejects_job_without_output_path(
    authenticated_client, sync_session
):
    job = Job(
        id=str(uuid4()),
        status=JobStatus.DONE,
        source=JobSource.MANUAL,
        media_path="/test/video.mp4",
        output_path=None,
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

    assert response.status_code == 400
    assert "output file" in response.json()["detail"].lower()


def test_patch_language_rejects_invalid_code(
    authenticated_client, sync_session, tmp_path
):
    job = _make_job(sync_session, tmp_path)

    response = authenticated_client.patch(
        f"/api/jobs/{job.id}/language", json={"language_code": "not-a-code"}
    )

    assert response.status_code in (400, 422)


def test_patch_language_renames_file_and_updates_job(
    authenticated_client, sync_session, tmp_path
):
    job = _make_job(sync_session, tmp_path)
    old_path = job.output_path

    response = authenticated_client.patch(
        f"/api/jobs/{job.id}/language", json={"language_code": "fr"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["language_code"] == "fr"
    assert data["needs_language_review"] is False
    assert data["output_path"] == str(tmp_path / "movie.fr.srt")

    import os

    assert not os.path.exists(old_path)
    assert os.path.exists(data["output_path"])

    sync_session.expire_all()
    refreshed = sync_session.get(Job, job.id)
    assert refreshed.language_code == "fr"
    assert refreshed.needs_language_review is False
    assert refreshed.output_path == str(tmp_path / "movie.fr.srt")


def test_patch_language_on_rename_failure_returns_error_not_silent(
    authenticated_client, sync_session, tmp_path
):
    """A failed rename must surface as an error, not be swallowed - otherwise
    the DB and filesystem would silently disagree about the file's language."""
    job = _make_job(
        sync_session,
        tmp_path,
        output_path=str(tmp_path / "does-not-exist.und.srt"),
    )

    response = authenticated_client.patch(
        f"/api/jobs/{job.id}/language", json={"language_code": "fr"}
    )

    assert response.status_code >= 500
