"""Tests for progress reporting functionality."""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline import Pipeline
from src.transcription_client import TranscriptionClient


class TestProgressReporting:
    """Test progress reporting functionality."""

    def test_pipeline_progress_callback_signature(self):
        """Test that pipeline accepts progress callback with percentage parameter."""
        progress_messages = []
        
        def mock_progress_callback(message: str, percentage: int = None):
            progress_messages.append((message, percentage))
        
        # Test that callback is called with correct signature
        with patch('src.pipeline.extract_audio') as mock_extract, \
             patch('src.pipeline.needs_splitting') as mock_needs_splitting, \
             patch('src.pipeline.split_audio') as mock_split, \
             patch.object(TranscriptionClient, 'transcribe_audio_with_timestamps') as mock_transcribe, \
             patch('src.pipeline.SubtitleGenerator.generate') as mock_generate, \
             patch('os.path.exists') as mock_exists:
            
            # Mock file existence checks
            mock_exists.return_value = True
            
            mock_extract.return_value = '/tmp/test.wav'
            mock_needs_splitting.return_value = False
            mock_transcribe.return_value = [{'start': 0, 'end': 1, 'text': 'test'}]
            mock_generate.return_value = '/tmp/output.srt'
            
            pipeline = Pipeline(
                api_key='test_key',
                progress_callback=mock_progress_callback,
                verbose_progress=True
            )
            
            # This should not raise an error
            pipeline.process_video('dev/test_video.mp4', '/tmp/output.srt')
            
            # Verify progress callback was called
            assert len(progress_messages) > 0
            
            # Verify some calls have percentages
            percentage_calls = [msg for msg in progress_messages if msg[1] is not None]
            assert len(percentage_calls) > 0
            
            # Verify percentages are in valid range
            for _, percentage in percentage_calls:
                assert 0 <= percentage <= 100

    def test_transcription_client_upload_progress(self):
        """Test that transcription client reports upload progress."""
        progress_messages = []
        
        def mock_progress_callback(message: str, percentage: int = None):
            progress_messages.append((message, percentage))
        
        # Create a temporary audio file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_audio:
            tmp_audio.write(b'\x00' * 2048)  # 2KB audio file
            tmp_audio_path = tmp_audio.name
        
        try:
            client = TranscriptionClient(
                api_key='test_key',
                progress_callback=mock_progress_callback
            )
            
            # Mock the Mistral API call
            with patch('src.transcription_client.Mistral') as mock_mistral:
                mock_client = MagicMock()
                mock_mistral.return_value = mock_client
                mock_response = MagicMock()
                mock_response.text = 'test transcription'
                mock_client.audio.transcriptions.complete.return_value = mock_response
                
                # This should call progress callback with upload progress
                client.transcribe_audio(
                    tmp_audio_path,
                    segment_number=1,
                    total_segments=1
                )
                
                # Verify upload progress was reported
                upload_messages = [msg for msg in progress_messages if 'Uploading' in msg[0]]
                assert len(upload_messages) > 0
                
                # Verify progress includes percentages
                percentage_messages = [msg for msg in upload_messages if msg[1] is not None]
                assert len(percentage_messages) > 0
                
                # Verify we have 0% and 100% messages
                percentages = [msg[1] for msg in percentage_messages]
                assert 0 in percentages
                assert 100 in percentages
                
        finally:
            os.unlink(tmp_audio_path)

    def test_progress_percentage_ranges(self):
        """Test that progress percentages are within valid ranges."""
        progress_messages = []
        
        def mock_progress_callback(message: str, percentage: int = None):
            if percentage is not None:
                progress_messages.append(percentage)
        
        with patch('src.pipeline.extract_audio') as mock_extract, \
             patch('src.pipeline.needs_splitting') as mock_needs_splitting, \
             patch('src.pipeline.split_audio') as mock_split, \
             patch.object(TranscriptionClient, 'transcribe_audio_with_timestamps') as mock_transcribe, \
             patch('src.pipeline.SubtitleGenerator.generate') as mock_generate:
            
            mock_extract.return_value = '/tmp/test.wav'
            mock_needs_splitting.return_value = False
            mock_transcribe.return_value = [{'start': 0, 'end': 1, 'text': 'test'}]
            mock_generate.return_value = '/tmp/output.srt'
            
            pipeline = Pipeline(
                api_key='test_key',
                progress_callback=mock_progress_callback,
                verbose_progress=True
            )
            
            pipeline.process_video('dev/test_video.mp4', '/tmp/output.srt')
            
            # All percentages should be between 0 and 100
            for percentage in progress_messages:
                assert 0 <= percentage <= 100, f"Invalid percentage: {percentage}"

    def test_progress_stage_transitions(self):
        """Test that progress transitions through expected stages."""
        progress_messages = []
        
        def mock_progress_callback(message: str, percentage: int = None):
            progress_messages.append((message, percentage))
        
        with patch('src.pipeline.extract_audio') as mock_extract, \
             patch('src.pipeline.needs_splitting') as mock_needs_splitting, \
             patch('src.pipeline.split_audio') as mock_split, \
             patch.object(TranscriptionClient, 'transcribe_audio_with_timestamps') as mock_transcribe, \
             patch('src.pipeline.SubtitleGenerator.generate') as mock_generate:
            
            mock_extract.return_value = '/tmp/test.wav'
            mock_needs_splitting.return_value = False
            mock_transcribe.return_value = [{'start': 0, 'end': 1, 'text': 'test'}]
            mock_generate.return_value = '/tmp/output.srt'
            
            pipeline = Pipeline(
                api_key='test_key',
                progress_callback=mock_progress_callback,
                verbose_progress=True
            )
            
            pipeline.process_video('dev/test_video.mp4', '/tmp/output.srt')
            
            # Extract stage messages
            stage_messages = {}
            for message, percentage in progress_messages:
                if percentage is not None:
                    if 'Extracting audio' in message:
                        stage_messages['extraction'] = percentage
                    elif 'Transcribing audio' in message:
                        stage_messages['transcription'] = percentage
                    elif 'Generating' in message:
                        stage_messages['generation'] = percentage
            
            # Verify we have progress for each stage
            assert 'extraction' in stage_messages
            assert 'transcription' in stage_messages
            assert 'generation' in stage_messages
            
            # Verify stage percentages are in expected ranges
            assert 0 < stage_messages['extraction'] <= 30
            assert 30 <= stage_messages['transcription'] <= 75
            assert 75 <= stage_messages['generation'] <= 100

    def test_no_progress_without_verbose_flag(self):
        """Test that progress percentages are not reported without verbose flag."""
        progress_messages = []
        
        def mock_progress_callback(message: str, percentage: int = None):
            progress_messages.append((message, percentage))
        
        with patch('src.pipeline.extract_audio') as mock_extract, \
             patch('src.pipeline.needs_splitting') as mock_needs_splitting, \
             patch('src.pipeline.split_audio') as mock_split, \
             patch.object(TranscriptionClient, 'transcribe_audio_with_timestamps') as mock_transcribe, \
             patch('src.pipeline.SubtitleGenerator.generate') as mock_generate:
            
            mock_extract.return_value = '/tmp/test.wav'
            mock_needs_splitting.return_value = False
            mock_transcribe.return_value = [{'start': 0, 'end': 1, 'text': 'test'}]
            mock_generate.return_value = '/tmp/output.srt'
            
            pipeline = Pipeline(
                api_key='test_key',
                progress_callback=mock_progress_callback,
                verbose_progress=False  # No verbose progress
            )
            
            pipeline.process_video('dev/test_video.mp4', '/tmp/output.srt')
            
            # Should have messages but no percentages
            percentage_messages = [msg for msg in progress_messages if msg[1] is not None]
            assert len(percentage_messages) == 0

    def test_upload_progress_with_large_file(self):
        """Test upload progress with a larger file to verify chunking."""
        progress_messages = []
        
        def mock_progress_callback(message: str, percentage: int = None):
            progress_messages.append((message, percentage))
        
        # Create a larger temporary audio file (5MB)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_audio:
            tmp_audio.write(b'\x00' * (5 * 1024 * 1024))  # 5MB audio file
            tmp_audio_path = tmp_audio.name
        
        try:
            client = TranscriptionClient(
                api_key='test_key',
                progress_callback=mock_progress_callback
            )
            
            # Mock the Mistral API call
            with patch('src.transcription_client.Mistral') as mock_mistral:
                mock_client = MagicMock()
                mock_mistral.return_value = mock_client
                mock_response = MagicMock()
                mock_response.text = 'test transcription'
                mock_client.audio.transcriptions.complete.return_value = mock_response
                
                # This should call progress callback multiple times for chunked upload
                client.transcribe_audio(
                    tmp_audio_path,
                    segment_number=1,
                    total_segments=1
                )
                
                # Verify we have multiple progress updates
                upload_messages = [msg for msg in progress_messages if 'Uploading' in msg[0]]
                assert len(upload_messages) > 2  # Should have multiple chunks
                
                # Verify we have intermediate percentages
                percentages = [msg[1] for msg in upload_messages if msg[1] is not None]
                assert len(percentages) > 2
                
                # Verify percentages are increasing
                for i in range(1, len(percentages)):
                    assert percentages[i] >= percentages[i-1]
                
        finally:
            os.unlink(tmp_audio_path)

    def test_progress_completion(self):
        """Test that progress reaches 100% on completion."""
        progress_messages = []
        
        def mock_progress_callback(message: str, percentage: int = None):
            progress_messages.append((message, percentage))
        
        with patch('src.pipeline.extract_audio') as mock_extract, \
             patch('src.pipeline.needs_splitting') as mock_needs_splitting, \
             patch('src.pipeline.split_audio') as mock_split, \
             patch.object(TranscriptionClient, 'transcribe_audio_with_timestamps') as mock_transcribe, \
             patch('src.pipeline.SubtitleGenerator.generate') as mock_generate:
            
            mock_extract.return_value = '/tmp/test.wav'
            mock_needs_splitting.return_value = False
            mock_transcribe.return_value = [{'start': 0, 'end': 1, 'text': 'test'}]
            mock_generate.return_value = '/tmp/output.srt'
            
            pipeline = Pipeline(
                api_key='test_key',
                progress_callback=mock_progress_callback,
                verbose_progress=True
            )
            
            pipeline.process_video('dev/test_video.mp4', '/tmp/output.srt')
            
            # Should end with 100%
            final_messages = [msg for msg in progress_messages if msg[1] == 100]
            assert len(final_messages) > 0
            
            # Last percentage message should be 100%
            percentage_messages = [msg for msg in progress_messages if msg[1] is not None]
            if percentage_messages:
                last_percentage = percentage_messages[-1][1]
                assert last_percentage == 100

    def test_progress_with_multiple_segments(self):
        """Test progress reporting with multiple audio segments."""
        progress_messages = []
        
        def mock_progress_callback(message: str, percentage: int = None):
            progress_messages.append((message, percentage))
        
        with patch('src.pipeline.extract_audio') as mock_extract, \
             patch('src.pipeline.needs_splitting') as mock_needs_splitting, \
             patch('src.pipeline.split_audio') as mock_split, \
             patch.object(TranscriptionClient, 'transcribe_audio_with_timestamps') as mock_transcribe, \
             patch('src.pipeline.SubtitleGenerator.generate') as mock_generate:
            
            mock_extract.return_value = '/tmp/test.wav'
            mock_needs_splitting.return_value = True
            mock_split.return_value = ['/tmp/segment1.wav', '/tmp/segment2.wav']
            mock_transcribe.return_value = [{'start': 0, 'end': 1, 'text': 'test'}]
            mock_generate.return_value = '/tmp/output.srt'
            
            pipeline = Pipeline(
                api_key='test_key',
                progress_callback=mock_progress_callback,
                verbose_progress=True
            )
            
            pipeline.process_video('dev/test_video.mp4', '/tmp/output.srt')
            
            # Should have segment progress messages
            segment_messages = [msg for msg in progress_messages if 'segment' in msg[0].lower()]
            assert len(segment_messages) > 0
            
            # Should have progress for both segments
            segment_1_messages = [msg for msg in segment_messages if '1/2' in msg[0] or '1 of 2' in msg[0]]
            segment_2_messages = [msg for msg in segment_messages if '2/2' in msg[0] or '2 of 2' in msg[0]]
            assert len(segment_1_messages) > 0
            assert len(segment_2_messages) > 0