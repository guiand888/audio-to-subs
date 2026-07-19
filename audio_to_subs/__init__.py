"""parolesub — convert video/audio to subtitles with AI transcription."""

from importlib import metadata
from pathlib import Path

_PACKAGE_NAME = "parolesub"


def _normalize(raw: str) -> str:
    """Return a display version, always prefixed with a single ``v``."""
    raw = raw.strip()
    if not raw:
        return "unknown"
    return raw if raw.startswith("v") else f"v{raw}"


def _resolve_version() -> str:
    """Resolve the running application version.

    The version has a single source of truth: the repo-root ``VERSION`` file.
    It is baked into the installed package metadata at build/install time
    (see setup.py / pyproject.toml), so the code reports its own version
    regardless of how it is deployed (compose, Helm, bare ``pip install``…).

    Priority:
    1. Installed package metadata (baked from ``VERSION`` at install time).
    2. ``VERSION`` file next to the package (defensive fallback).
    3. ``"unknown"`` as a last resort.
    """
    try:
        return _normalize(metadata.version(_PACKAGE_NAME))
    except metadata.PackageNotFoundError:
        pass

    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    if version_file.is_file():
        return _normalize(version_file.read_text())

    return "unknown"


__version__ = _resolve_version()
