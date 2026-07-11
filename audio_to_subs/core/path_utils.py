"""Path utilities for media file handling.

Provides utilities for:
- Path validation against configured root directories
- Output path generation based on source media paths
- Media type detection (movie vs TV)
"""

import os
from pathlib import Path, PurePosixPath
from typing import Literal


def _is_within(path: str, root: str) -> bool:
    """Check if a path is within a root directory (safely).

    Uses realpath() to resolve symlinks and checks proper path boundaries.

    Args:
        path: Path to check
        root: Root directory that should contain path

    Returns:
        True if path is within root, False otherwise
    """
    try:
        resolved_path = os.path.realpath(path)
        resolved_root = os.path.realpath(root)

        # Ensure root ends with separator for proper boundary checking
        if not resolved_root.endswith(os.sep):
            resolved_root += os.sep

        # Check if path is exactly the root or within it
        return resolved_path == resolved_root.rstrip(
            os.sep
        ) or resolved_path.startswith(resolved_root)
    except (OSError, ValueError):
        # Path doesn't exist or is invalid
        return False


def validate_media_path(
    media_path: str,
    movies_root: str | None = None,
    tv_root: str | None = None,
) -> tuple[bool, str | None]:
    """Validate that a media path is within allowed root directories.

    Args:
        media_path: The path to validate
        movies_root: Root path for movies (e.g., "/movies")
        tv_root: Root path for TV series (e.g., "/tv")

    Returns:
        Tuple of (is_valid, error_message)
        is_valid is True if path is valid or if no roots are configured
        error_message contains details if validation fails
    """
    if not movies_root and not tv_root:
        # No roots configured, allow any path
        return True, None

    # Check against configured roots using safe path comparison
    if movies_root and _is_within(media_path, movies_root):
        return True, None

    if tv_root and _is_within(media_path, tv_root):
        return True, None

    return (
        False,
        f"Path '{media_path}' is not within configured root directories "
        f"(movies: {movies_root}, tv: {tv_root})",
    )


def contains_traversal(path: str) -> bool:
    """Detect path-traversal attempts in a media/output path.

    Returns ``True`` if ``path`` contains parent-directory (``..``) references
    such as ``../../etc/passwd`` or ``/movies/../secret``. The check is purely
    lexical so it works whether or not the referenced files exist, and is
    independent of the configured root directories.

    Args:
        path: The path to inspect.

    Returns:
        ``True`` if the path references a parent directory (traversal), else
        ``False``.
    """
    try:
        parts = PurePosixPath(path).parts
    except (OSError, ValueError):
        # Unparseable path is treated as a traversal attempt.
        return True
    return ".." in parts


def get_media_type(
    media_path: str,
    movies_root: str | None = None,
    tv_root: str | None = None,
) -> Literal["movie", "tv", "unknown"]:
    """Determine media type based on path.

    Args:
        media_path: Path to analyze
        movies_root: Root path for movies
        tv_root: Root path for TV series

    Returns:
        "movie" if path is under movies_root
        "tv" if path is under tv_root
        "unknown" if path doesn't match either or roots aren't configured
    """
    if not movies_root and not tv_root:
        return "unknown"

    if movies_root and _is_within(media_path, movies_root):
        return "movie"

    if tv_root and _is_within(media_path, tv_root):
        return "tv"

    return "unknown"


def generate_output_path(
    media_path: str,
    language_code: str | None = None,
    output_format: str = "srt",
    subtitles_same_directory: bool = True,
) -> str:
    """Generate output subtitle path based on media path.

    When subtitles_same_directory is True, saves subtitle alongside media file
    with naming convention: {media_filename}.{language_code}.{format}

    Args:
        media_path: Path to source media file
        language_code: Language code (e.g., "en", "fr")
        output_format: Subtitle format (e.g., "srt", "vtt")
        subtitles_same_directory: Whether to save in same directory

    Returns:
        Generated output path
    """
    media_path_obj = Path(media_path)

    if subtitles_same_directory:
        # Save alongside source file
        filename = media_path_obj.stem
        if language_code:
            output_filename = f"{filename}.{language_code}.{output_format}"
        else:
            output_filename = f"{filename}.{output_format}"
        return str(media_path_obj.parent / output_filename)
    else:
        # Fallback: use original behavior (would need output directory)
        # For backward compatibility, return a path in /output
        if language_code:
            return f"/output/{media_path_obj.stem}.{language_code}.{output_format}"
        else:
            return f"/output/{media_path_obj.stem}.{output_format}"


def normalize_path(path: str) -> str:
    """Normalize a path for consistent comparison.

    Args:
        path: Path to normalize

    Returns:
        Normalized path with consistent separators and no trailing slashes
    """
    return os.path.normpath(path.rstrip("/\\"))


def path_is_absolute(path: str) -> bool:
    """Check if a path is absolute.

    Args:
        path: Path to check

    Returns:
        True if path is absolute, False otherwise
    """
    return os.path.isabs(path)


def paths_overlap(path1: str, path2: str) -> bool:
    """Check if two paths overlap (one is parent of the other).

    Args:
        path1: First path
        path2: Second path

    Returns:
        True if paths overlap, False otherwise
    """
    try:
        resolved1 = os.path.realpath(path1)
        resolved2 = os.path.realpath(path2)

        # Ensure both end with separator for proper prefix matching
        if not resolved1.endswith(os.sep):
            resolved1 += os.sep
        if not resolved2.endswith(os.sep):
            resolved2 += os.sep

        return (
            resolved1.startswith(resolved2)
            or resolved2.startswith(resolved1)
            or resolved1.rstrip(os.sep) == resolved2.rstrip(os.sep)
        )
    except (OSError, ValueError):
        # If paths don't exist or are invalid, assume no overlap
        return False
