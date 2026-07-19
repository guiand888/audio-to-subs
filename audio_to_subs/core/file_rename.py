"""Rename a subtitle file's language suffix on disk."""

import os
from pathlib import Path


def compute_rename_target(
    current_path: str, old_code: str | None, new_code: str
) -> str:
    """Compute the target path for ``rename_subtitle_language`` without renaming.

    Strips *all* trailing ``.<old_code>`` occurrences from the stem (so already
    broken files like ``stem.fr.fr.srt`` collapse to a single ``.<new_code>``
    suffix) and falls back to appending the new suffix to the bare stem if
    old_code isn't actually present.

    Pure function: performs no filesystem writes. Used by callers that must
    check for an existing target *before* committing to the rename (M6.g
    language-correction overwrite guard).
    """
    path = Path(current_path)
    stem = path.stem

    if old_code:
        old_lang_suffix = f".{old_code}"
        while stem.endswith(old_lang_suffix):
            stem = stem[: -len(old_lang_suffix)]

    new_name = f"{stem}.{new_code}{path.suffix}"
    return str(path.parent / new_name)


def rename_subtitle_language(
    current_path: str, old_code: str | None, new_code: str
) -> str:
    """Rename `stem.<old_code>.<ext>` to `stem.<new_code>.<ext>` on disk.

    Strips *all* trailing ``.<old_code>`` occurrences from the stem so
    already-broken files (e.g. ``stem.fr.fr.srt`` from the double-append
    bug) collapse to a single ``.<new_code>`` suffix.

    Falls back to appending the new suffix to the bare stem if old_code
    isn't actually present in the filename (defensive - shouldn't happen
    for jobs that reached DONE with a language-suffixed output path).

    Returns the new path. Raises OSError if the rename fails - callers
    must not swallow this: unlike best-effort hooks elsewhere in this
    codebase, a failed rename here would leave the DB and the filesystem
    silently disagreeing about the file's language.
    """
    new_path = compute_rename_target(current_path, old_code, new_code)
    os.rename(current_path, new_path)
    return new_path
