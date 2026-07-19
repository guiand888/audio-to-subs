"""Tests for worker job runner (claim -> process -> persist)."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from audio_to_subs.core.cancel import Cancelled
from audio_to_subs.core.pipeline import PipelineResult
from audio_to_subs.db.models import Job, JobLog, JobSource, JobStatus, LogLevel, Setting
from audio_to_subs.queue_.claim import ClaimedJob
from audio_to_subs.queue_.events import set_job_progress
from audio_to_subs.worker.runner import (
    JobResult,
    WorkerDeps,
    _get_db_settings,
    persist_log,
    persist_result,
    run_job,
)


def make_claimed_job(**overrides) -> ClaimedJob:
    """Build a ClaimedJob with sensible test defaults."""
    defaults = {
        "id": str(uuid4()),
        "media_path": "/test/video.mp4",
        "output_path": "/test/output.srt",
        "language_code": "en",
        "language_mode": "explicit",
        "output_format": "srt",
        "source": JobSource.MANUAL.value,
        "source_ref": None,
    }
    defaults.update(overrides)
    return ClaimedJob(**defaults)


def make_worker_deps(
    session, redis=None, settings=None, database_url=None
) -> WorkerDeps:
    """Build WorkerDeps with a mocked redis client and minimal settings."""
    if redis is None:
        redis = AsyncMock()
    if settings is None:
        settings = MagicMock(
            SUBTITLES_SAME_DIRECTORY=True,
            mistral_model="voxtral-mini-2602",
            mistral_rate_usd_per_minute=0.0,
            mistral_input_token_rate_usd=None,
            mistral_output_token_rate_usd=None,
        )
    if database_url is None:
        from audio_to_subs.api.settings import get_settings

        settings_obj = get_settings()
        database_url = settings_obj.DATABASE_URL
    return WorkerDeps(
        session=session,
        redis=redis,
        settings=settings,
        mistral_api_key="test-key",
        database_url=database_url,
    )


class TestPersistResult:
    """Test persist_result writes job outcome fields to the DB."""

    @pytest.mark.asyncio
    async def test_persist_result_success_updates_status_and_cost(
        self, mock_db_session
    ):
        job = Job(
            id=str(uuid4()),
            status=JobStatus.RUNNING,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
            output_format="srt",
        )
        mock_db_session.add(job)
        await mock_db_session.flush()
        await mock_db_session.commit()

        job_id = job.id
        result = JobResult(
            status=JobStatus.DONE,
            audio_duration_seconds=42.5,
            mistral_usage_json='{"prompt_tokens": 10}',
            estimated_cost_usd=0.01,
        )

        await persist_result(mock_db_session, job_id, result)

        # persist_result writes via raw SQL, bypassing the session identity
        # map — expire the cached object so the re-fetch hits the DB.
        mock_db_session.expire_all()
        refreshed = (
            await mock_db_session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        assert refreshed.status == JobStatus.DONE.value
        assert refreshed.audio_duration_seconds == 42.5
        assert refreshed.estimated_cost_usd == 0.01
        assert refreshed.finished_at is not None

    @pytest.mark.asyncio
    async def test_persist_result_clears_redis_snapshot(self, mock_db_session):
        """On terminal persist, the Redis live snapshot must be cleared so the
        next GET sees the DB's authoritative terminal progress."""
        job = Job(
            id=str(uuid4()),
            status=JobStatus.RUNNING,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
            output_format="srt",
        )
        mock_db_session.add(job)
        await mock_db_session.flush()
        await mock_db_session.commit()
        job_id = job.id

        redis = FakeRedis()
        await set_job_progress(
            redis, job_id, percent=73, stage="formatting", message="almost"
        )

        result = JobResult(status=JobStatus.DONE)
        await persist_result(mock_db_session, job_id, result, redis=redis)

        raw = await redis.hgetall(f"job:progress:{job_id}")
        assert raw == {}

        mock_db_session.expire_all()
        refreshed = (
            await mock_db_session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        assert refreshed.status == JobStatus.DONE.value

    @pytest.mark.asyncio
    async def test_persist_result_failure_sets_error_message(self, mock_db_session):
        job = Job(
            id=str(uuid4()),
            status=JobStatus.RUNNING,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
            output_format="srt",
        )
        mock_db_session.add(job)
        await mock_db_session.flush()
        await mock_db_session.commit()

        job_id = job.id
        result = JobResult(status=JobStatus.FAILED, error_message="boom")

        await persist_result(mock_db_session, job_id, result)

        mock_db_session.expire_all()
        refreshed = (
            await mock_db_session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        assert refreshed.status == JobStatus.FAILED.value
        assert refreshed.error_message == "boom"

    @pytest.mark.asyncio
    async def test_persist_result_nonexistent_job_does_not_raise(self, mock_db_session):
        """Updating a job id that doesn't exist should be a no-op, not an error."""
        result = JobResult(status=JobStatus.DONE)
        await persist_result(mock_db_session, str(uuid4()), result)

    @pytest.mark.asyncio
    async def test_persist_result_auto_mode_uses_detected_language(
        self, mock_db_session
    ):
        """Auto mode overwrites language_code with Mistral's detected language
        and does NOT flag the job for review."""
        job = Job(
            id=str(uuid4()),
            status=JobStatus.RUNNING,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
            output_format="srt",
            language_mode="auto",
        )
        mock_db_session.add(job)
        await mock_db_session.flush()
        await mock_db_session.commit()

        job_id = job.id
        result = JobResult(
            status=JobStatus.DONE,
            detected_language="fr",
            language_mode="auto",
        )

        await persist_result(mock_db_session, job_id, result)

        mock_db_session.expire_all()
        refreshed = (
            await mock_db_session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        assert refreshed.language_code == "fr"
        assert refreshed.mistral_detected_language == "fr"
        assert refreshed.needs_language_review is False

    @pytest.mark.asyncio
    async def test_persist_result_auto_mode_falls_back_to_und_and_flags_review(
        self, mock_db_session
    ):
        """When Mistral reports no language in auto mode, the job falls back
        to the "und" sentinel and is flagged for review."""
        job = Job(
            id=str(uuid4()),
            status=JobStatus.RUNNING,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
            output_format="srt",
            language_mode="auto",
        )
        mock_db_session.add(job)
        await mock_db_session.flush()
        await mock_db_session.commit()

        job_id = job.id
        result = JobResult(
            status=JobStatus.DONE,
            detected_language=None,
            language_mode="auto",
        )

        await persist_result(mock_db_session, job_id, result)

        mock_db_session.expire_all()
        refreshed = (
            await mock_db_session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        assert refreshed.language_code == "und"
        assert refreshed.mistral_detected_language is None
        assert refreshed.needs_language_review is True

    @pytest.mark.asyncio
    async def test_persist_result_explicit_mode_does_not_overwrite_language_code(
        self, mock_db_session
    ):
        """Explicit mode keeps the user's selection - only the raw detected
        language is captured (for the passive mismatch flag), never used to
        override the filename/DB language_code."""
        job = Job(
            id=str(uuid4()),
            status=JobStatus.RUNNING,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
            output_format="srt",
            language_code="en",
            language_mode="explicit",
        )
        mock_db_session.add(job)
        await mock_db_session.flush()
        await mock_db_session.commit()

        job_id = job.id
        result = JobResult(
            status=JobStatus.DONE,
            detected_language="fr",
            language_mode="explicit",
        )

        await persist_result(mock_db_session, job_id, result)

        mock_db_session.expire_all()
        refreshed = (
            await mock_db_session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        assert refreshed.language_code == "en"
        assert refreshed.mistral_detected_language == "fr"
        assert refreshed.needs_language_review is False

    @pytest.mark.asyncio
    async def test_persist_result_updates_output_path(self, mock_db_session):
        """persist_result must write result.output_path to job.output_path so
        the DB always reflects the actual on-disk file (critical in auto
        mode where the language isn't known at creation time)."""
        job = Job(
            id=str(uuid4()),
            status=JobStatus.RUNNING,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
            output_format="srt",
            output_path="/test/video.srt",
            language_mode="auto",
        )
        mock_db_session.add(job)
        await mock_db_session.flush()
        await mock_db_session.commit()

        job_id = job.id
        result = JobResult(
            status=JobStatus.DONE,
            output_path="/test/video.fr.srt",
            detected_language="fr",
            language_mode="auto",
        )

        await persist_result(mock_db_session, job_id, result)

        mock_db_session.expire_all()
        refreshed = (
            await mock_db_session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        assert refreshed.output_path == "/test/video.fr.srt"

    @pytest.mark.asyncio
    async def test_persist_result_preserves_output_path_when_none(
        self, mock_db_session
    ):
        """If result.output_path is None (e.g. failure), the existing
        job.output_path must not be clobbered."""
        job = Job(
            id=str(uuid4()),
            status=JobStatus.RUNNING,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
            output_format="srt",
            output_path="/test/video.fr.srt",
        )
        mock_db_session.add(job)
        await mock_db_session.flush()
        await mock_db_session.commit()

        job_id = job.id
        result = JobResult(
            status=JobStatus.FAILED,
            error_message="boom",
        )

        await persist_result(mock_db_session, job_id, result)

        mock_db_session.expire_all()
        refreshed = (
            await mock_db_session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one()
        assert refreshed.output_path == "/test/video.fr.srt"


class TestPersistLog:
    """Test persist_log writes a JobLog row."""

    @pytest.mark.asyncio
    async def test_persist_log_writes_entry(self, mock_db_session):
        from audio_to_subs.api.settings import get_settings

        job = Job(
            id=str(uuid4()),
            status=JobStatus.RUNNING,
            source=JobSource.MANUAL,
            media_path="/test/video.mp4",
            output_format="srt",
        )
        mock_db_session.add(job)
        await mock_db_session.flush()
        await mock_db_session.commit()

        # persist_log now opens its own short-lived session via database_url
        # (so the worker never holds a write transaction across the long
        # transcription). The per-test DB URL points at the same file DB.
        await persist_log(
            get_settings().DATABASE_URL, job.id, LogLevel.ERROR, "something failed"
        )

        rows = (
            (
                await mock_db_session.execute(
                    select(JobLog).where(JobLog.job_id == job.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].level == LogLevel.ERROR
        assert rows[0].message == "something failed"


class TestGetDbSettings:
    """Test _get_db_settings reads worker-relevant settings from the DB."""

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_settings(self, mock_db_session):
        from audio_to_subs.api.settings import get_settings

        settings = await _get_db_settings(get_settings().DATABASE_URL)
        assert settings == {}

    @pytest.mark.asyncio
    async def test_reads_known_settings_keys(self, mock_db_session):
        from audio_to_subs.api.settings import get_settings

        mock_db_session.add(Setting(key="mistral_model", value_json='"voxtral-large"'))
        mock_db_session.add(
            Setting(key="ignored_unknown_key", value_json='"should-not-appear"')
        )
        await mock_db_session.flush()
        await mock_db_session.commit()

        settings = await _get_db_settings(get_settings().DATABASE_URL)

        assert settings.get("mistral_model") == "voxtral-large"
        assert "ignored_unknown_key" not in settings

    @pytest.mark.asyncio
    async def test_parses_value_json_when_present(self, mock_db_session):
        from audio_to_subs.api.settings import get_settings

        mock_db_session.add(
            Setting(
                key="mistral_rate_usd_per_minute",
                value_json="0.02",
            )
        )
        await mock_db_session.flush()
        await mock_db_session.commit()

        settings = await _get_db_settings(get_settings().DATABASE_URL)

        assert settings.get("mistral_rate_usd_per_minute") == 0.02


class TestRunJob:
    """Test run_job's end-to-end orchestration with a mocked Pipeline."""

    @pytest.mark.asyncio
    async def test_run_job_success_publishes_done_and_returns_result(
        self, mock_db_session
    ):
        claimed = make_claimed_job()
        deps = make_worker_deps(mock_db_session)

        pipeline_result = PipelineResult(
            output_path="/test/output.srt",
            audio_duration_seconds=30.0,
            mistral_usage={"prompt_audio_seconds": 30.0},
            segments_count=2,
        )

        with patch("audio_to_subs.worker.runner.Pipeline") as mock_pipeline_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process_video.return_value = pipeline_result
            mock_pipeline_class.return_value = mock_pipeline

            result = await run_job(claimed, deps)

        assert result.status == JobStatus.DONE
        assert result.audio_duration_seconds == 30.0
        deps.redis.publish.assert_called()

    @pytest.mark.asyncio
    async def test_run_job_auto_mode_threads_detected_language_into_result(
        self, mock_db_session
    ):
        """run_job passes claimed.language_mode to Pipeline and carries the
        pipeline's detected_language + the job's language_mode into JobResult
        so persist_result can resolve the final language."""
        claimed = make_claimed_job(language_code=None, language_mode="auto")
        deps = make_worker_deps(mock_db_session)

        pipeline_result = PipelineResult(
            output_path="/test/output.fr.srt",
            audio_duration_seconds=30.0,
            mistral_usage=None,
            segments_count=1,
            detected_language="fr",
        )

        with patch("audio_to_subs.worker.runner.Pipeline") as mock_pipeline_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process_video.return_value = pipeline_result
            mock_pipeline_class.return_value = mock_pipeline

            result = await run_job(claimed, deps)

        assert result.status == JobStatus.DONE
        assert result.detected_language == "fr"
        assert result.language_mode == "auto"
        # Pipeline must be constructed in auto mode, not silently defaulted.
        _, pipeline_kwargs = mock_pipeline_class.call_args
        assert pipeline_kwargs["language_mode"] == "auto"

    @pytest.mark.asyncio
    async def test_run_job_cancelled_returns_cancelled_status(self, mock_db_session):
        claimed = make_claimed_job()
        deps = make_worker_deps(mock_db_session)

        with patch("audio_to_subs.worker.runner.Pipeline") as mock_pipeline_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process_video.side_effect = Cancelled("cancelled by user")
            mock_pipeline_class.return_value = mock_pipeline

            result = await run_job(claimed, deps)

        assert result.status == JobStatus.CANCELLED
        deps.redis.publish.assert_called()

    @pytest.mark.asyncio
    async def test_run_job_refuses_to_overwrite_existing_file(self, mock_db_session):
        """M6.g write-time guard: when the resolved output file already exists
        and the job was not created with overwrite=true, run_job fails the job
        with an `output_exists` error rather than clobbering the subtitle."""
        from audio_to_subs.core.pipeline import SubtitleFileExistsError

        claimed = make_claimed_job(overwrite=False)
        deps = make_worker_deps(mock_db_session)

        with patch("audio_to_subs.worker.runner.Pipeline") as mock_pipeline_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process_video.side_effect = SubtitleFileExistsError(
                "/test/existing.srt"
            )
            mock_pipeline_class.return_value = mock_pipeline

            result = await run_job(claimed, deps)

        assert result.status == JobStatus.FAILED
        assert result.error_message is not None
        assert "output_exists" in result.error_message
        deps.redis.publish.assert_called()

    @pytest.mark.asyncio
    async def test_run_job_threads_overwrite_flag_to_pipeline(self, mock_db_session):
        """The job's overwrite flag must reach the Pipeline constructor so the
        generator can decide whether to replace an existing file."""
        claimed = make_claimed_job(overwrite=True)
        deps = make_worker_deps(mock_db_session)

        pipeline_result = PipelineResult(
            output_path="/test/output.srt",
            audio_duration_seconds=30.0,
            mistral_usage=None,
            segments_count=1,
        )

        with patch("audio_to_subs.worker.runner.Pipeline") as mock_pipeline_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process_video.return_value = pipeline_result
            mock_pipeline_class.return_value = mock_pipeline

            await run_job(claimed, deps)

        _, pipeline_kwargs = mock_pipeline_class.call_args
        assert pipeline_kwargs["overwrite"] is True

    @pytest.mark.asyncio
    async def test_run_job_failure_persists_error_and_returns_failed_status(
        self, mock_db_session
    ):
        claimed = make_claimed_job()
        deps = make_worker_deps(mock_db_session)

        # Persist a job row so persist_log's FK write succeeds.
        job_row = Job(
            id=str(claimed.id),
            status=JobStatus.RUNNING,
            source=JobSource.MANUAL,
            media_path=claimed.media_path,
            output_format=claimed.output_format,
        )
        mock_db_session.add(job_row)
        await mock_db_session.flush()
        await mock_db_session.commit()

        with patch("audio_to_subs.worker.runner.Pipeline") as mock_pipeline_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process_video.side_effect = Exception("pipeline exploded")
            mock_pipeline_class.return_value = mock_pipeline

            result = await run_job(claimed, deps)

        assert result.status == JobStatus.FAILED
        assert "pipeline exploded" in result.error_message
        deps.redis.publish.assert_called()

        logs = (
            (
                await mock_db_session.execute(
                    select(JobLog).where(JobLog.job_id == str(claimed.id))
                )
            )
            .scalars()
            .all()
        )
        assert any("pipeline exploded" in log.message for log in logs)

    @pytest.mark.asyncio
    async def test_run_job_generates_output_path_when_not_provided(
        self, mock_db_session
    ):
        claimed = make_claimed_job(output_path="")
        deps = make_worker_deps(mock_db_session)

        pipeline_result = PipelineResult(
            output_path="/generated/output.srt",
            audio_duration_seconds=10.0,
            mistral_usage=None,
            segments_count=1,
        )

        with (
            patch("audio_to_subs.worker.runner.Pipeline") as mock_pipeline_class,
            patch(
                "audio_to_subs.worker.runner.generate_output_path"
            ) as mock_generate_path,
        ):
            mock_generate_path.return_value = "/generated/output.srt"
            mock_pipeline = MagicMock()
            mock_pipeline.process_video.return_value = pipeline_result
            mock_pipeline_class.return_value = mock_pipeline

            result = await run_job(claimed, deps)

        mock_generate_path.assert_called_once()
        assert result.status == JobStatus.DONE

    @pytest.mark.asyncio
    async def test_run_job_returns_output_path_in_result(self, mock_db_session):
        """run_job must carry the pipeline's actual output_path (which may
        differ from the creation-time path in auto mode) into the JobResult
        so persist_result can write it to the DB."""
        claimed = make_claimed_job(
            output_path="/test/video.srt",
            language_code=None,
            language_mode="auto",
        )
        deps = make_worker_deps(mock_db_session)

        pipeline_result = PipelineResult(
            output_path="/test/video.fr.srt",
            audio_duration_seconds=30.0,
            mistral_usage=None,
            segments_count=1,
            detected_language="fr",
        )

        with patch("audio_to_subs.worker.runner.Pipeline") as mock_pipeline_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process_video.return_value = pipeline_result
            mock_pipeline_class.return_value = mock_pipeline

            result = await run_job(claimed, deps)

        assert result.status == JobStatus.DONE
        assert result.output_path == "/test/video.fr.srt"


class TestRunJobBazarrRescan:
    """Cover the best-effort Bazarr rescan branch (M6 error-path coverage)."""

    @pytest.mark.asyncio
    async def test_run_job_bazarr_movie_triggers_rescan(self, mock_db_session):
        claimed = make_claimed_job(source=JobSource.BAZARR_MOVIE.value, source_ref="42")
        deps = make_worker_deps(mock_db_session)

        pipeline_result = PipelineResult(
            output_path="/test/output.srt",
            audio_duration_seconds=30.0,
            mistral_usage=None,
            segments_count=1,
        )

        with (
            patch("audio_to_subs.worker.runner.Pipeline") as mock_pipeline_class,
            patch(
                "audio_to_subs.worker.runner._rescan_bazarr_movie",
                new=AsyncMock(return_value=True),
            ) as mock_rescan,
        ):
            mock_pipeline = MagicMock()
            mock_pipeline.process_video.return_value = pipeline_result
            mock_pipeline_class.return_value = mock_pipeline

            result = await run_job(claimed, deps)

        assert result.status == JobStatus.DONE
        mock_rescan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_job_bazarr_rescan_failure_still_completes(self, mock_db_session):
        """A failing Bazarr rescan must not fail the job (best-effort)."""
        claimed = make_claimed_job(
            source=JobSource.BAZARR_EPISODE.value, source_ref="7"
        )
        deps = make_worker_deps(mock_db_session)

        pipeline_result = PipelineResult(
            output_path="/test/output.srt",
            audio_duration_seconds=30.0,
            mistral_usage=None,
            segments_count=1,
        )

        with (
            patch("audio_to_subs.worker.runner.Pipeline") as mock_pipeline_class,
            patch(
                "audio_to_subs.worker.runner._rescan_bazarr_episode",
                new=AsyncMock(side_effect=RuntimeError("bazarr down")),
            ),
        ):
            mock_pipeline = MagicMock()
            mock_pipeline.process_video.return_value = pipeline_result
            mock_pipeline_class.return_value = mock_pipeline

            result = await run_job(claimed, deps)

        assert result.status == JobStatus.DONE


class TestGetDbSettingsError:
    """Cover the settings-fetch failure branch (M6 error-path coverage)."""

    @pytest.mark.asyncio
    async def test_get_db_settings_failure_returns_empty(self, monkeypatch):
        """If the DB session raises, _get_db_settings must swallow it and
        return an empty dict rather than propagate."""
        import audio_to_subs.worker.runner as runner_module

        def _boom(*args, **kwargs):
            raise RuntimeError("db unreachable")

        monkeypatch.setattr(runner_module, "get_async_session", _boom)

        assert await _get_db_settings("sqlite+aiosqlite:///:memory:") == {}


class TestPersistResultErrors:
    """Cover persist_result's error branches (M6 error-path coverage)."""

    @pytest.mark.asyncio
    async def test_persist_result_integrity_error_is_swallowed(self, monkeypatch):
        """An IntegrityError during commit must be caught and logged, not
        raised to the caller."""
        session = AsyncMock()
        job = MagicMock()
        session.get.return_value = job
        session.commit.side_effect = IntegrityError("stmt", "params", "orig")

        await persist_result(session, "job-1", JobResult(status=JobStatus.DONE))

        session.rollback.assert_awaited()
