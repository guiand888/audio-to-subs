"""Tests for core/file_rename.py - subtitle language-suffix renaming."""

import os

import pytest

from audio_to_subs.core.file_rename import rename_subtitle_language


def test_rename_replaces_language_suffix(tmp_path):
    src = tmp_path / "movie.und.srt"
    src.write_text("subtitle content")

    new_path = rename_subtitle_language(str(src), "und", "fr")

    assert new_path == str(tmp_path / "movie.fr.srt")
    assert os.path.exists(new_path)
    assert not src.exists()


def test_rename_falls_back_to_appending_when_old_code_absent(tmp_path):
    src = tmp_path / "movie.srt"
    src.write_text("subtitle content")

    new_path = rename_subtitle_language(str(src), None, "fr")

    assert new_path == str(tmp_path / "movie.fr.srt")
    assert os.path.exists(new_path)


def test_rename_falls_back_when_old_code_not_in_filename(tmp_path):
    src = tmp_path / "movie.srt"
    src.write_text("subtitle content")

    # old_code given but doesn't match the actual filename - append instead
    # of corrupting the stem.
    new_path = rename_subtitle_language(str(src), "en", "fr")

    assert new_path == str(tmp_path / "movie.fr.srt")


def test_rename_raises_on_missing_source_file(tmp_path):
    missing = tmp_path / "nonexistent.und.srt"

    with pytest.raises(OSError):
        rename_subtitle_language(str(missing), "und", "fr")


def test_rename_preserves_directory(tmp_path):
    subdir = tmp_path / "movies"
    subdir.mkdir()
    src = subdir / "movie.und.vtt"
    src.write_text("WEBVTT")

    new_path = rename_subtitle_language(str(src), "und", "de")

    assert new_path == str(subdir / "movie.de.vtt")
    assert os.path.exists(new_path)
