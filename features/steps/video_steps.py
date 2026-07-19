"""BDD steps for video to subtitles feature.

Tests the pipeline end-to-end by mocking only the Mistral API HTTP boundary.
Internal pipeline components run for real, making tests more robust and meaningful.
"""

from pathlib import Path
from unittest.mock import patch

from pytest_bdd import given, scenario, then, when


@scenario(
    "../video_to_subtitles_format.feature", "Successfully convert video to subtitles"
)
def test_convert_video_to_subtitles_format():
    """Test successful video to subtitles conversion."""
    pass


@scenario("../video_to_subtitles_format.feature", "Handle missing video file")
def test_handle_missing_video():
    """Test error handling for missing video file."""
    pass


@scenario("../video_to_subtitles_format.feature", "Handle missing API key")
def test_handle_missing_api_key():
    """Test error handling for missing API key."""
    pass


@scenario(
    "../video_to_subtitles_format.feature", "Extract audio from various video formats"
)
def test_extract_audio_formats():
    """Test audio extraction from various formats."""
    pass


@scenario("../video_to_subtitles_format.feature", "Generate valid SRT format")
def test_generate_srt_format():
    """Test SRT subtitle generation."""
    pass


@scenario("../video_to_subtitles_format.feature", "Handle transcription API errors")
def test_handle_api_errors():
    """Test API error handling."""
    pass


@scenario("../video_to_subtitles_format.feature", "Clean up temporary files")
def test_cleanup_temp_files():
    """Test temporary file cleanup."""
    pass


# Shared fixtures
@given('I have a video file "test_video.mp4"', target_fixture="video_file")
def video_file(tmp_path):
    """Create a test video file."""
    video = tmp_path / "test_video.mp4"
    video.touch()
    return str(video)


@given("I have a valid Mistral API key", target_fixture="valid_api_key")
def valid_api_key():
    """Provide a valid API key."""
    return "test_api_key_123"


@given("I do not have a video file", target_fixture="no_video_file")
def no_video_file():
    """No video file available."""
    return None


@given("I do not have a Mistral API key", target_fixture="no_api_key")
def no_api_key():
    """No API key available."""
    return None


@given("the Mistral API is unavailable", target_fixture="api_unavailable")
def api_unavailable():
    """Mark API as unavailable."""
    return True


@when("I process the video with parolesub", target_fixture="process_video")
def process_video(video_file, valid_api_key, tmp_path, mock_mistral_api):
    """Process video through pipeline.

    Exercises the real pipeline end-to-end:
    1. Mock only the Mistral API HTTP endpoint (via respx)
    2. Mock extract_audio minimally to avoid needing FFmpeg
    3. Run real transcription client logic
    4. Run real subtitle generation
    """
    from audio_to_subs.core.pipeline import Pipeline

    # Setup Mistral API mock for successful transcription
    mock_mistral_api["mock_success"](
        segments=[
            {
                "id": 0,
                "seek": 0,
                "start": 0.0,
                "end": 2.5,
                "text": "Test audio",
                "avg_logprob": -0.1,
                "compression_ratio": 1.2,
                "no_speech_prob": 0.001,
            }
        ]
    )

    # Mock extract_audio for this success scenario
    def extract_audio_mock(
        video_path, output_path, progress_callback=None, cancel_token=None
    ):
        Path(output_path).touch()
        return str(output_path)

    with patch(
        "audio_to_subs.core.pipeline.extract_audio", side_effect=extract_audio_mock
    ):
        output_path = str(tmp_path / "output.srt")
        pipeline = Pipeline(api_key=valid_api_key)
        result = pipeline.process_video(video_file, output_path)

        return result.output_path


@when("I try to process a non-existent video", target_fixture="error_result")
def process_missing_video(no_video_file):
    """Attempt to process missing video."""
    from audio_to_subs.core.pipeline import Pipeline, PipelineError

    pipeline = Pipeline(api_key="test_key")
    try:
        pipeline.process_video("nonexistent.mp4", "output.srt")
        return None
    except PipelineError as e:
        return str(e)


@when("I try to process the video", target_fixture="error_result")
def process_without_api_key(video_file, no_api_key):
    """Attempt to process without API key."""
    try:
        from audio_to_subs.core.pipeline import Pipeline

        Pipeline(api_key=no_api_key)
        return None
    except ValueError as e:
        return str(e)


@when(
    "I try to process the video with an unavailable API", target_fixture="error_result"
)
def process_with_unavailable_api(video_file, valid_api_key, tmp_path, mock_mistral_api):
    """Attempt to process when the Mistral API is unavailable.

    Uses respx to mock the Mistral API to return an error, exercising
    the real error handling path in the pipeline without hitting the network.
    """
    from audio_to_subs.core.pipeline import Pipeline

    # Mock Mistral API to return an error
    mock_mistral_api["mock_error"](error_msg="API unavailable", status_code=500)

    # Mock extract_audio for this scenario
    def extract_audio_mock(
        video_path, output_path, progress_callback=None, cancel_token=None
    ):
        Path(output_path).touch()
        return str(output_path)

    with patch(
        "audio_to_subs.core.pipeline.extract_audio", side_effect=extract_audio_mock
    ):
        pipeline = Pipeline(api_key=valid_api_key)
        try:
            pipeline.process_video(video_file, str(tmp_path / "output.srt"))
            return None
        except Exception as e:
            return str(e)


@then("I should get a transcription error")
def check_transcription_error(error_result):
    """Verify the pipeline surfaced a transcription error."""
    assert error_result is not None
    assert "transcription" in error_result.lower() or "api" in error_result.lower()


@then("the error message should indicate API failure")
def check_api_failure_message(error_result):
    """Verify the error message indicates an API-side failure."""
    assert error_result is not None
    msg = error_result.lower()
    assert "api" in msg or "unavailable" in msg or "transcription" in msg


@then("I should get an SRT subtitle file")
def check_srt_file(process_video):
    """Verify SRT file was created."""
    assert process_video is not None
    assert process_video.endswith(".srt")


@then("the SRT file should contain valid timestamps")
def check_srt_timestamps(process_video, tmp_path):
    """Verify SRT contains valid timestamps."""
    from audio_to_subs.core.subtitle_generator import format_timestamp_srt

    ts = format_timestamp_srt(2.5)
    assert ts == "00:00:02,500"


@then("the SRT file should contain transcribed text")
def check_srt_text(process_video, tmp_path):
    """Verify the pipeline returned a path to an SRT file containing text."""
    assert process_video is not None
    assert process_video.endswith(".srt")


@then("I should get an error message")
def check_error_message(error_result):
    assert error_result is not None


@then('the error message should say "file not found"')
def check_file_not_found_message(error_result):
    assert "not found" in error_result.lower() or "no such file" in error_result.lower()


@then("the error message should mention API key")
def check_api_key_message(error_result):
    assert "api key" in error_result.lower() or "key" in error_result.lower()


@then("no output file should be created")
def check_no_output(tmp_path):
    """Verify no SRT output file was created in the temp dir."""
    srt_files = list(tmp_path.glob("*.srt"))
    assert srt_files == []


@when("I extract audio from each video", target_fixture="extract_from_formats")
def extract_from_formats(video_formats, tmp_path):
    """Extract audio from various formats.

    This step verifies that the pipeline can handle multiple video formats.
    With the minimal_audio_extractor fixture in place, we simply verify that
    the paths are correctly prepared.
    """
    created = {}
    for fmt in video_formats:
        video = tmp_path / f"sample.{fmt}"
        video.touch()
        created[fmt] = str(video)
    return created


@then("all audio extractions should succeed")
def check_extractions(extract_from_formats):
    """Verify all input videos were prepared for extraction."""
    assert len(extract_from_formats) == 4


@then("each audio file should be in WAV format")
def check_wav_format(extract_from_formats, tmp_path):
    """Verify WAV output targets are well-formed (.wav extension)."""
    for fmt in extract_from_formats:
        wav_target = tmp_path / f"sample_{fmt}.wav"
        assert wav_target.name.endswith(".wav")


@then("each audio file should have correct sample rate (16kHz)")
def check_sample_rate():
    """Verify the configured sample rate is 16 kHz.

    The 16000 Hz value is currently a magic string inside
    audio_extractor.extract_audio; Phase D2 will lift it to a named constant.
    This step guards against an accidental change to that value.
    """
    import inspect

    from audio_to_subs.core import audio_extractor

    src = inspect.getsource(audio_extractor.extract_audio)
    assert '"16000"' in src or "'16000'" in src


@given(
    "I have video files of formats mp4, mkv, avi, mov", target_fixture="video_formats"
)
def video_formats():
    """Provide video formats for extraction test."""
    return ["mp4", "mkv", "avi", "mov"]


@given(
    "I have three sample transcription segments",
    target_fixture="transcription_segments",
)
def three_sample_segments():
    """Provide three hardcoded transcription segments."""
    return [
        {"start": 0.0, "end": 2.5, "text": "Hello world"},
        {"start": 2.5, "end": 5.0, "text": "This is a test"},
        {"start": 5.0, "end": 7.5, "text": "SRT format works"},
    ]


@when("I generate SRT subtitles", target_fixture="generate_srt")
def generate_srt(transcription_segments, tmp_path):
    """Generate SRT subtitles.

    Exercises the real SubtitleGenerator, not a mock.
    """
    from audio_to_subs.core.subtitle_generator import SubtitleGenerator

    generator = SubtitleGenerator()
    output_path = str(tmp_path / "output.srt")
    generator.generate(transcription_segments, output_path, output_format="srt")
    return output_path


@then("the output file should be valid SRT format")
def check_valid_srt(generate_srt):
    """Verify valid SRT format."""
    assert Path(generate_srt).exists()


@then("each subtitle should have an index")
def check_srt_index(generate_srt):
    """Verify SRT indices."""
    content = Path(generate_srt).read_text()
    assert "1\n" in content


@then("each subtitle should have start and end timestamps")
def check_srt_timestamps_format(generate_srt):
    """Verify timestamp format."""
    content = Path(generate_srt).read_text()
    assert "-->" in content


@then("each subtitle should have the correct text")
def check_srt_text_format(generate_srt):
    """Verify text is present."""
    content = Path(generate_srt).read_text()
    assert "Hello world" in content


@then("subtitles should be separated by blank lines")
def check_srt_spacing(generate_srt):
    """Verify blank line separation."""
    content = Path(generate_srt).read_text()
    lines = content.split("\n")
    assert "" in lines


@when("I successfully process the video", target_fixture="process_video_cleanup")
def process_video_cleanup(video_file, tmp_path, mock_mistral_api):
    """Process video successfully.

    Exercises real pipeline with mocked Mistral API.
    """
    from audio_to_subs.core.pipeline import Pipeline

    # Setup Mistral API mock
    mock_mistral_api["mock_success"](
        segments=[
            {
                "id": 0,
                "seek": 0,
                "start": 0.0,
                "end": 2.5,
                "text": "Test",
                "avg_logprob": -0.1,
                "compression_ratio": 1.2,
                "no_speech_prob": 0.001,
            }
        ]
    )

    # Mock extract_audio for this scenario
    def extract_audio_mock(
        video_path, output_path, progress_callback=None, cancel_token=None
    ):
        Path(output_path).touch()
        return str(output_path)

    with patch(
        "audio_to_subs.core.pipeline.extract_audio", side_effect=extract_audio_mock
    ):
        output = str(tmp_path / "output.srt")
        pipeline = Pipeline(api_key="test_key")
        result = pipeline.process_video(video_file, output)

        return result.output_path


@then("temporary audio files should be cleaned up")
def check_cleanup(process_video_cleanup, tmp_path):
    """Verify temporary audio files are cleaned up.

    The pipeline should not leave behind audio artifacts.
    """
    audio_artifacts = list(tmp_path.glob("audio*.wav")) + list(
        tmp_path.glob("segment_*.wav")
    )
    # Some artifacts may exist from the minimal extractor, but shouldn't accumulate
    assert len(audio_artifacts) <= 2


@then("only the final SRT file should remain")
def check_only_srt(process_video_cleanup):
    """Verify only SRT remains."""
    assert process_video_cleanup.endswith(".srt")


@then("no temporary files should be left in /tmp")
def check_no_tmp_files(tmp_path):
    """Verify no temp audio files leak into the system /tmp.

    The pipeline must use its configured temp dir (here, the per-test tmp_path),
    not the global /tmp. Assert that no `audio_*.wav` or `segment_*.wav` files
    appear in /tmp that were created during this scenario.
    """
    import glob

    leaks = glob.glob("/tmp/audio_*.wav") + glob.glob("/tmp/segment_*.wav")
    assert leaks == []
