"""Rename a subtitle file's language suffix on disk."""

import os
from pathlib import Path


def rename_subtitle_language(
    current_path: str, old_code: str | None, new_code: str
) -> str:
    """Rename `stem.<old_code>.<ext>` to `stem.<new_code>.<ext>` on disk.

    Falls back to appending the new suffix to the bare stem if old_code
    isn't actually present in the filename (defensive - shouldn't happen
    for jobs that reached DONE with a language-suffixed output path).

    Returns the new path. Raises OSError if the rename fails - callers
    must not swallow this: unlike best-effort hooks elsewhere in this
    codebase, a failed rename here would leave the DB and the filesystem
    silently disagreeing about the file's language.
    """
    path = Path(current_path)
    name = path.name
    old_suffix = f".{old_code}{path.suffix}" if old_code else None

    if old_suffix and name.endswith(old_suffix):
        new_name = name[: -len(old_suffix)] + f".{new_code}{path.suffix}"
    else:
        new_name = f"{path.stem}.{new_code}{path.suffix}"

    new_path = path.parent / new_name
    os.rename(current_path, new_path)
    return str(new_path)
