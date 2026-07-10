"""Tests for structured progress in pipeline."""

from audio_to_subs.core.pipeline import (
    Pipeline,
    PipelineResult,
    ProgressEvent,
)


class TestPipelineResult:
    """Tests for PipelineResult dataclass."""

    def test_creation(self) -> None:
        """Test creating a PipelineResult."""
        result = PipelineResult(
            output_path="/path/to/output.srt",
            audio_duration_seconds=60.5,
            mistral_usage={"prompt_audio_seconds": 60},
            segments_count=1,
        )

        assert result.output_path == "/path/to/output.srt"
        assert result.audio_duration_seconds == 60.5
        assert result.mistral_usage == {"prompt_audio_seconds": 60}
        assert result.segments_count == 1

    def test_fspath(self) -> None:
        """Test __fspath__ method."""
        result = PipelineResult(
            output_path="/path/to/output.srt",
            audio_duration_seconds=60.0,
            mistral_usage=None,
            segments_count=0,
        )

        assert result.__fspath__() == "/path/to/output.srt"

    def test_str(self) -> None:
        """Test __str__ method."""
        result = PipelineResult(
            output_path="/path/to/output.srt",
            audio_duration_seconds=60.0,
            mistral_usage=None,
            segments_count=0,
        )

        assert str(result) == "/path/to/output.srt"

    def test_repr(self) -> None:
        """Test __repr__ method."""
        result = PipelineResult(
            output_path="/path/to/output.srt",
            audio_duration_seconds=60.0,
            mistral_usage={"key": "value"},
            segments_count=5,
        )

        repr_str = repr(result)
        assert "PipelineResult" in repr_str
        assert "/path/to/output.srt" in repr_str
        assert "segments_count=5" in repr_str


class TestPipelineStructuredProgress:
    """Tests for pipeline with structured progress callback."""

    def test_structured_callback_receives_events(self) -> None:
        """Test that Pipeline stores the structured progress callback."""
        events: list[ProgressEvent] = []

        def structured_callback(event: ProgressEvent) -> None:
            events.append(event)

        # Just verify Pipeline stores the callback — running the full pipeline
        # would require FFmpeg.  The _extract_audio attribute no longer exists
        # (it was renamed to extract_audio), so patch that name at the module level.
        pipeline = Pipeline(
            api_key="test-key",
            structured_progress_callback=structured_callback,
            temp_dir="/tmp",
        )

        assert pipeline._structured_progress_callback is not None

    def test_pipeline_with_cancel_token(self) -> None:
        """Test that Pipeline stores the cancel token."""
        from audio_to_subs.core.cancel import CancelToken

        token = CancelToken()

        pipeline = Pipeline(
            api_key="test-key",
            cancel_token=token,
            temp_dir="/tmp",
        )

        assert pipeline._cancel_token is token


class TestStepAccounting:
    """Tests for M5.8 step accounting and continuous extract/split progress."""

    def _run_with_events(self, mocked_pipeline_deps, tmp_path, duration: float):
        """Drive a full (mocked) process_video, returning captured events."""
        events: list[ProgressEvent] = []

        def structured_callback(event: ProgressEvent) -> None:
            events.append(event)

        mocked_pipeline_deps["extract_audio"].return_value = str(tmp_path / "a.wav")
        mocked_pipeline_deps["needs_splitting"].return_value = duration > 900
        mocked_pipeline_deps["get_audio_duration"].return_value = duration
        mocked_pipeline_deps["transcribe_audio_with_timestamps"].return_value = [
            {"start": 0, "end": 1, "text": "x"}
        ]
        mocked_pipeline_deps["generate"].return_value = str(tmp_path / "out.srt")

        pipeline = Pipeline(
            api_key="test-key",
            structured_progress_callback=structured_callback,
            max_audio_length=900,
            temp_dir=str(tmp_path),
        )
        pipeline.process_video(str(tmp_path / "in.mp4"), str(tmp_path / "out.srt"))
        return events

    def test_step_total_is_three_when_no_split(self, mocked_pipeline_deps, tmp_path):
        events = self._run_with_events(mocked_pipeline_deps, tmp_path, 60.0)
        extract_events = [e for e in events if e.get("stage") == "extract"]
        assert extract_events
        # The start event fires before duration is known (step_total None); the
        # completion event (after extraction) carries the resolved total.
        assert extract_events[-1].get("step_total") == 3
        assert extract_events[-1].get("step_index") == 1

    def test_step_total_is_four_when_splitting(self, mocked_pipeline_deps, tmp_path):
        events = self._run_with_events(mocked_pipeline_deps, tmp_path, 1200.0)
        split_events = [e for e in events if e.get("stage") == "split"]
        assert split_events
        assert split_events[-1].get("step_total") == 4
        assert split_events[-1].get("step_index") == 2

    def test_extract_percent_within_range(self, mocked_pipeline_deps, tmp_path):
        events = self._run_with_events(mocked_pipeline_deps, tmp_path, 60.0)
        extract_events = [e for e in events if e.get("stage") == "extract"]
        percents = [e["percent"] for e in extract_events]
        assert min(percents) >= 10
        assert max(percents) <= 25

    def test_init_and_done_have_no_step(self, mocked_pipeline_deps, tmp_path):
        events = self._run_with_events(mocked_pipeline_deps, tmp_path, 60.0)
        init = [e for e in events if e.get("stage") == "init"]
        done = [e for e in events if e.get("stage") == "done"]
        assert init and done
        assert init[0].get("step_index") is None
        assert done[0].get("step_index") is None

    def test_step_for_mapping(self) -> None:
        pipeline = Pipeline(
            api_key="test-key", structured_progress_callback=lambda e: None
        )
        pipeline._step_total = 3
        assert pipeline._step_for("extract") == (1, 3)
        assert pipeline._step_for("transcribe") == (2, 3)
        assert pipeline._step_for("generate") == (3, 3)
        pipeline._step_total = 4
        assert pipeline._step_for("extract") == (1, 4)
        assert pipeline._step_for("split") == (2, 4)
        assert pipeline._step_for("transcribe") == (3, 4)
        assert pipeline._step_for("generate") == (4, 4)
        # init/done and unresolved total return no step
        assert pipeline._step_for("init") == (None, None)
        assert pipeline._step_for("done") == (None, None)
        pipeline._step_total = None
        assert pipeline._step_for("extract") == (None, None)

    def test_subprogress_callback_maps_percent(self) -> None:
        events: list[ProgressEvent] = []
        pipeline = Pipeline(
            api_key="test-key", structured_progress_callback=events.append
        )
        cb = pipeline._subprogress_callback("extract", 10, 25)
        assert cb is not None
        # ffmpeg reports 50% of the way through the decode
        cb("Extracting audio: 5.0 / 10.0s (50.0%)")
        assert len(events) == 1
        assert events[0]["stage"] == "extract"
        assert events[0]["percent"] == 17  # 10 + (25-10)*0.5

    def test_subprogress_callback_none_without_structured(self, tmp_path) -> None:
        pipeline = Pipeline(api_key="test-key", temp_dir=str(tmp_path))
        assert pipeline._subprogress_callback("extract", 10, 25) is None
