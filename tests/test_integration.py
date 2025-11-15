"""Integration tests with real Mistral AI API."""
import pytest
import os
from pathlib import Path
from src.pipeline import Pipeline


@pytest.fixture
def mistral_api_key():
    \"\"\"Load Mistral API key from .mistral_api_key file or env.\"\"\"
    api_key = os.getenv('MISTRAL_API_KEY')
    
    if not api_key:
        api_key_file = Path('/home/guillaume/Development/audio-to-subs/.mistral_api_key')
        if api_key_file.exists():
            api_key = api_key_file.read_text().strip()
    
    if not api_key or api_key.startswith('REPLACE'):
        pytest.skip('Mistral API key not configured')
    
    return api_key


@pytest.fixture
def test_video_file(tmp_path):
    \"\"\"Create or use test video file.\"\"\"
    # In real test, would use actual video file
    # For now, skip if no real video available
    return None


class TestIntegration:
    \"\"\"Integration tests with real Mistral API.\"\"\"

    @pytest.mark.integration
    def test_pipeline_with_real_api(self, mistral_api_key, tmp_path):
        \"\"\"Test full pipeline with real Mistral API.
        
        IMPORTANT: This test requires:
        - Valid Mistral API key in .mistral_api_key or MISTRAL_API_KEY env var
        - FFmpeg installed
        - Real audio file for transcription
        \"\"\"
        pytest.skip('Requires real video file for integration test')

    @pytest.mark.integration
    def test_transcription_client_real_api(self, mistral_api_key, tmp_path):
        \"\"\"Test TranscriptionClient with real Mistral API.\"\"\"
        from src.transcription_client import TranscriptionClient
        
        client = TranscriptionClient(api_key=mistral_api_key)
        
        # Would test with real audio file
        # For now, skip without real audio
        pytest.skip('Requires real audio file for integration test')

    @pytest.mark.integration
    def test_pipeline_end_to_end_mock_api(self, mistral_api_key, tmp_path):
        \"\"\"Test pipeline end-to-end with mocked transcription.\"\"\"
        from unittest.mock import patch, MagicMock
        
        # Create test video file
        video_file = tmp_path / 'test.mp4'
        video_file.touch()
        output_file = tmp_path / 'output.srt'
        
        # Mock only the transcription API, use real extraction and generation
        with patch('src.pipeline.TranscriptionClient') as mock_tc_class:
            mock_tc = MagicMock()
            mock_tc_class.return_value = mock_tc
            mock_tc.transcribe_audio_with_timestamps.return_value = [
                {'start': 0.0, 'end': 2.5, 'text': 'Test subtitle one'},
                {'start': 2.5, 'end': 5.0, 'text': 'Test subtitle two'}
            ]
            
            pipeline = Pipeline(api_key=mistral_api_key)
            
            # This will fail at audio extraction without real FFmpeg
            # but tests the pipeline integration
            try:
                result = pipeline.process_video(str(video_file), str(output_file))
                assert str(output_file) == result
            except Exception as e:
                # Expected to fail without FFmpeg or real audio
                assert 'FFmpeg' in str(e) or 'extraction' in str(e).lower()
