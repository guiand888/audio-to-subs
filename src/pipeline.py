"""Pipeline orchestrator for video to subtitles conversion."""
from pathlib import Path
from typing import Optional, Callable, List, Dict
import tempfile
import os

from src.audio_extractor import extract_audio, FFmpegNotFoundError, AudioExtractionError
from src.transcription_client import TranscriptionClient, TranscriptionError
from src.subtitle_generator import SubtitleGenerator, SubtitleFormatError


class PipelineError(Exception):
    """Raised when pipeline processing fails."""
    pass


class Pipeline:
    """Orchestrate video to subtitles conversion pipeline."""

    def __init__(
        self,
        api_key: str,
        progress_callback: Optional[Callable[[str], None]] = None,
        temp_dir: Optional[str] = None
    ):
        """Initialize pipeline.
        
        Args:
            api_key: Mistral AI API key
            progress_callback: Optional callback for progress updates
            temp_dir: Optional temporary directory for intermediate files
            
        Raises:
            ValueError: If API key is not provided
        """
        if not api_key:
            raise ValueError("API key is required")
        
        self.api_key = api_key
        self.progress_callback = progress_callback
        self.temp_dir = temp_dir or tempfile.gettempdir()
        self.transcription_client = TranscriptionClient(api_key=api_key)
        self.subtitle_generator = SubtitleGenerator()

    def process_video(self, video_path: str, output_path: str, output_format: str = "srt") -> str:
        """Convert video to subtitles.
        
        Args:
            video_path: Path to input video file
            output_path: Path to write output subtitle file
            output_format: Output subtitle format (srt, vtt, webvtt, sbv). Default: srt
            
        Returns:
            Path to generated subtitle file
            
        Raises:
            PipelineError: If any stage fails
        """
        audio_path = None
        
        try:
            # Stage 1: Extract audio
            self._progress("Extracting audio from video...")
            audio_path = self._extract_audio(video_path)
            
            # Stage 2: Transcribe audio
            self._progress("Transcribing audio with Mistral AI...")
            segments = self._transcribe_audio(audio_path)
            
            # Stage 3: Generate subtitles
            self._progress(f"Generating {output_format.upper()} subtitles...")
            output = self._generate_subtitles(segments, output_path, output_format)
            
            self._progress("Complete! Subtitles generated successfully.")
            return output
            
        finally:
            # Cleanup temp audio file
            if audio_path and Path(audio_path).exists():
                try:
                    os.remove(audio_path)
                except OSError:
                    pass  # Ignore cleanup errors

    def _extract_audio(self, video_path: str) -> str:
        """Extract audio from video.
        
        Args:
            video_path: Path to video file
            
        Returns:
            Path to extracted audio file
            
        Raises:
            PipelineError: If extraction fails
        """
        try:
            video_file = Path(video_path)
            if not video_file.exists():
                raise FileNotFoundError(f"Video file not found: {video_path}")
            
            # Generate temp audio file path
            audio_path = Path(self.temp_dir) / f"audio_{video_file.stem}.wav"
            
            return extract_audio(video_path, str(audio_path))
            
        except FileNotFoundError as e:
            raise PipelineError(f"Video file not found: {str(e)}")
        except (FFmpegNotFoundError, AudioExtractionError) as e:
            raise PipelineError(f"Audio extraction failed: {str(e)}")
        except Exception as e:
            raise PipelineError(f"Audio extraction failed: {str(e)}")

    def _transcribe_audio(self, audio_path: str) -> List[Dict]:
        """Transcribe audio to text with timestamps.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            List of transcription segments
            
        Raises:
            PipelineError: If transcription fails
        """
        try:
            return self.transcription_client.transcribe_audio_with_timestamps(audio_path)
        except TranscriptionError as e:
            raise PipelineError(f"Transcription failed: {str(e)}")
        except Exception as e:
            raise PipelineError(f"Transcription failed: {str(e)}")

    def _generate_subtitles(self, segments: List[Dict], output_path: str, output_format: str = "srt") -> str:
        """Generate subtitle file in specified format.
        
        Args:
            segments: Transcription segments
            output_path: Path to write subtitle file
            output_format: Output subtitle format (srt, vtt, webvtt, sbv)
            
        Returns:
            Path to generated subtitle file
            
        Raises:
            PipelineError: If generation fails
        """
        try:
            return self.subtitle_generator.generate(segments, output_path, output_format)
        except SubtitleFormatError as e:
            raise PipelineError(f"Subtitle generation failed: {str(e)}")
        except Exception as e:
            raise PipelineError(f"Subtitle generation failed: {str(e)}")

    def _progress(self, message: str) -> None:
        """Call progress callback if provided.
        
        Args:
            message: Progress message
        """
        if self.progress_callback:
            self.progress_callback(message)
