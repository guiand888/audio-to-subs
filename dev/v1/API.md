# API Reference

For programmatic usage of audio-to-subs as a library.

## Basic Usage

```python
from src.pipeline import Pipeline

# Initialize pipeline
pipeline = Pipeline(api_key="your_key")

# Process single video
output = pipeline.process_video(
    video_path="video.mp4",
    output_path="subtitles.srt",
    output_format="srt"  # srt, vtt, webvtt, sbv
)
```

## Batch Processing

```python
jobs = [
    {"input": "video1.mp4", "output": "sub1.srt"},
    {"input": "video2.mp4", "output": "sub2.vtt", "format": "vtt"}
]
results = pipeline.process_batch(jobs)
```

## Progress Callbacks

```python
def on_progress(message: str, percentage: int = None):
    if percentage:
        print(f"[{percentage}%] {message}")
    else:
        print(f"[Progress] {message}")

pipeline = Pipeline(
    api_key="your_key",
    progress_callback=on_progress,
    verbose_progress=True
)
```

## Progress Stages

1. **Audio Extraction (0-25%)**: Extracting audio from video file
2. **Audio Upload (25-50%)**: Uploading audio to Mistral AI
3. **Transcription Processing (50-75%)**: Processing transcription results
4. **Subtitle Generation (75-100%)**: Generating final subtitle files

## Supported Formats

- `srt` - SubRip (default)
- `vtt` - WebVTT
- `webvtt` - WebVTT
- `sbv` - YouTube subtitles
