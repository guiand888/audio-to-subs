"""Transcription client for Mistral AI Voxtral Mini."""
from pathlib import Path
from typing import Any

from mistralai import Mistral
from mistralai.models import File


class TranscriptionError(Exception):
    """Raised when transcription fails."""
    pass


class AudioFileError(Exception):
    """Raised when audio file is invalid or not found."""
    pass


class TranscriptionClient:
    """Client for transcribing audio using Mistral AI Voxtral Mini."""

    def __init__(self, api_key: str):
        """Initialize transcription client.
        
        Args:
            api_key: Mistral AI API key
            
        Raises:
            ValueError: If API key is not provided
        """
        if not api_key:
            raise ValueError("API key is required")
        
        self.api_key = api_key
        self.client = Mistral(api_key=api_key)

    def transcribe_audio(self, audio_path: str) -> str:
        """Transcribe audio file to text.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Transcribed text
            
        Raises:
            AudioFileError: If audio file not found
            TranscriptionError: If transcription fails
        """
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise AudioFileError(f"Audio file not found: {audio_path}")
        
        try:
            with open(audio_path, "rb") as audio_file:
                file_obj = File(content=audio_file.read(), fileName=Path(audio_path).name, contentType="audio/wav")
                response = self.client.audio.transcriptions.complete(
                    model="mistral-voxtral-mini-2501",
                    file=file_obj
                )
            return response.text
        except Exception as e:
            raise TranscriptionError(f"Transcription failed: {str(e)}") from e

    def transcribe_audio_with_timestamps(self, audio_path: str) -> list[dict[str, Any]]:
        """Transcribe audio with timestamp information.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            List of segments with start, end times and text
            
        Raises:
            AudioFileError: If audio file not found
            TranscriptionError: If transcription fails
        """
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise AudioFileError(f"Audio file not found: {audio_path}")
        
        try:
            with open(audio_path, "rb") as audio_file:
                file_obj = File(content=audio_file.read(), fileName=Path(audio_path).name, contentType="audio/wav")
                response = self.client.audio.transcriptions.complete(
                    model="mistral-voxtral-mini-2501",
                    file=file_obj,
                    timestamp_granularities=["segment"]
                )
            
            segments = []
            if hasattr(response, 'segments'):
                for segment in response.segments:
                    segments.append({
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text
                    })
            
            return segments
        except Exception as e:
            raise TranscriptionError(f"Transcription failed: {str(e)}") from e
