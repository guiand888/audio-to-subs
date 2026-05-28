# audio-to-subs

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
![Coverage](https://raw.githubusercontent.com/guiand888/audio-to-subs/badges/coverage.svg)
[![Tests](https://github.com/guiand888/audio-to-subs/actions/workflows/tests.yml/badge.svg)](https://github.com/guiand888/audio-to-subs/actions/workflows/tests.yml)

<img src="https://upload.wikimedia.org/wikipedia/commons/e/e6/Mistral_AI_logo_%282025%E2%80%93%29.svg" alt="Mistral" width="20" height="20" /> Convert video audio to subtitles using Mistral Voxtral Mini transcription.

## Features
- Extract audio from video files (mp4, mkv, avi, etc.)
- AI transcription using [Mistral Voxtral Mini](https://docs.mistral.ai/models/model-cards/voxtral-mini-25-07)
- Generate subtitles in SRT, VTT, SBV formats
- Single and batch processing
- Language code support (en, fr, es, de, etc.)
- Automatic filename generation (video.en.srt)

## Requirements
- Podman/Docker **or** Python 3.9+
- Mistral AI API key
- FFmpeg (included in containers)

## Quick Start

### Container (Recommended)
1. **Set API key:**
   ```bash
   echo -n "your_api_key" | podman secret create mistral_api_key -
   ```

2. **Run:**
   ```bash
   podman run --rm --userns=keep-id \
     --secret mistral_api_key,type=env,target=MISTRAL_API_KEY \
     -v ./videos:/input:ro,Z -v ./subs:/output:Z \
     audio-to-subs:latest -i /input/video.mp4 -o /output/video.srt
   ```

### Python venv
```bash
git clone https://github.com/guiand888/audio-to-subs.git
cd audio-to-subs
python3 -m venv venv
source venv/bin/activate
pip install -e .
export MISTRAL_API_KEY=your_api_key
audio-to-subs -i video.mp4 -o subtitles.srt
```

## Usage

### Single Video
```bash
# Basic (SRT)
podman run --rm --userns=keep-id \
  --secret mistral_api_key,type=env,target=MISTRAL_API_KEY \
  -v ./videos:/input:ro,Z -v ./subs:/output:Z \
  audio-to-subs:latest -i /input/video.mp4 -o /output/video.srt

# VTT format
... --format vtt

# With language code
... -o /output/video.srt --language en
```

### Batch Processing
Create `audio-to-subs.yaml`:
```yaml
jobs:
  - input: /input/video1.mp4
    output: /output/video1.srt
  - input: /input/video2.mp4
    output: /output/video2.vtt
    format: vtt
```
Run:
```bash
podman run --rm --userns=keep-id \
  --secret mistral_api_key,type=env,target=MISTRAL_API_KEY \
  -v $(pwd):/work:Z,rslave \
  audio-to-subs:latest --config /work/audio-to-subs.yaml
```

## Output Formats
SRT (default), VTT, SBV

## Subtitle Naming

Output files follow: `filename.language_code.format`

Examples: `movie.en.srt`, `show.s01e01.fr.vtt`

Supported language codes: en, fr, es, de, it, pt, ru, zh, ja, ko (ISO 639-1/2)

## Troubleshooting

**Permission denied:** Use `--userns=keep-id`

**API key missing:** Set via `--api-key` or `MISTRAL_API_KEY` env var

**Large files:** Auto-split >15min

## License
AGPLv3
