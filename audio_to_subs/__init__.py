"""parolesub — convert video/audio to subtitles with AI transcription."""

import os
from importlib import metadata


def _resolve_version() -> str:
    """Resolve the running application version.

    Priority:
    1. ``APP_VERSION`` env var — injected as a Docker ENV from the compose
       build ARG (the single source of truth: repo-root VERSION / .env).
    2. Installed package metadata (``pip install .`` records pyproject version).
    3. ``"unknown"`` as a last resort.
    """
    env_version = os.environ.get("APP_VERSION")
    if env_version:
        return env_version

    try:
        return metadata.version("parolesub")
    except metadata.PackageNotFoundError:
        return "unknown"


__version__ = _resolve_version()
