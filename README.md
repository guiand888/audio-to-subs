# parolesub

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![standard-readme compliant](https://img.shields.io/badge/readme-standard-brightgreen.svg)](https://github.com/RichardLitt/standard-readme)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
![Coverage](https://raw.githubusercontent.com/guiand888/parolesub/badges/coverage.svg)
[![Tests](https://github.com/guiand888/parolesub/actions/workflows/tests.yml/badge.svg)](https://github.com/guiand888/parolesub/actions/workflows/tests.yml)

Convert video audio to subtitles using Mistral Voxtral Mini transcription.

![parolesub frontend screenshot](docs/assets/screenshot-frontpage.png)

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Contributing](#contributing)
- [License](#license)

## Background

parolesub is a self-hosted web application that automates video transcription for media libraries. It integrates with Bazarr to detect missing subtitles, queues transcription jobs, and processes them using Mistral's Voxtral Mini model. The system includes a web UI for monitoring progress, viewing history, and managing settings.

The original CLI functionality is preserved - you can still run one-off transcriptions from the command line while the web application handles automated workflows.

## Install

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
     parolesub:latest -i /input/video.mp4 -o /output/video.srt
   ```

### Local development (`nix develop`)
```bash
git clone https://github.com/guiand888/parolesub.git
cd parolesub
nix develop   # bootstraps a .venv and installs deps automatically
export MISTRAL_API_KEY=your_api_key
parolesub -i video.mp4 -o subtitles.srt
```

### Web Application Deployment

For the full web application with Bazarr integration:

1. Create an external media volume:
   ```bash
   docker volume create media
   ```

2. Create secret files:
   ```bash
   mkdir -p .secrets && chmod 700 .secrets
   echo "your-mistral-key"  > .secrets/mistral_api_key
   echo "your-bazarr-key"   > .secrets/bazarr_api_key
   openssl rand -hex 32     > .secrets/session_secret
   echo "yourStrongPass!"   > .secrets/admin_password
   chmod 600 .secrets/*
   ```

3. Set environment variables:
   ```bash
   export BAZARR_URL="http://bazarr.lan:6767"
   export PATH_MAPPINGS_JSON='[{"/data/media","/mnt/media"}]'
   export ADMIN_USERNAME="admin"
   export FRONTEND_PORT=8080
   ```

4. Bring up the stack:
   ```bash
   podman compose up -d
   ```

5. Visit http://localhost:8080 and log in as admin.

## Usage

### Single Video (CLI)

```bash
# Basic (SRT)
podman run --rm --userns=keep-id \
  --secret mistral_api_key,type=env,target=MISTRAL_API_KEY \
  -v ./videos:/input:ro,Z -v ./subs:/output:Z \
  parolesub:latest -i /input/video.mp4 -o /output/video.srt

# VTT format
... --format vtt

# With language code
... -o /output/video.srt --language en
```

### Batch Processing (CLI)

Create `parolesub.yaml`:
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
  parolesub:latest --config /work/parolesub.yaml
```

### Web Application Workflow

1. **Setup**: Deploy using the container method above
2. **Configuration**: Configure Bazarr URL and API key in Settings
3. **Detection**: Bazarr integration automatically detects media missing subtitles
4. **Queue**: Items appear in the Wanted list in the web UI
5. **Process**: Click "Transcribe" to queue jobs for automatic processing
6. **Monitor**: Watch progress in the Queue page with live updates
7. **Complete**: Finished jobs appear in History with cost tracking

The Bazarr poller runs automatically and updates the Wanted list. When the "Track Items with No Subtitles" setting is enabled, it will also show items with no subtitles in any language.

### Output Formats

SRT (default), VTT, SBV

### Subtitle Naming

Output files follow: `filename.language_code.format`

Examples: `movie.en.srt`, `show.s01e01.fr.vtt`

Supported language codes: en, fr, es, de, it, pt, ru, zh, ja, ko (ISO 639-1/2)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and contribution guidelines.

## License

AGPLv3 - see [LICENSE](LICENSE) file for details.