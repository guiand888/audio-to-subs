"""Tests for path utilities."""

import os
import tempfile

from audio_to_subs.core.path_utils import (
    generate_output_path,
    get_media_type,
    normalize_path,
    path_is_absolute,
    paths_overlap,
    validate_media_path,
)


class TestValidateMediaPath:
    """Tests for validate_media_path function."""

    def test_no_roots_configured_allows_any_path(self) -> None:
        """When no roots configured, any path should be allowed."""
        is_valid, error = validate_media_path("/some/random/path", None, None)
        assert is_valid is True
        assert error is None

    def test_path_within_movies_root(self) -> None:
        """Path within movies root should be valid."""
        is_valid, error = validate_media_path(
            "/movies/action/movie.mp4", "/movies", None
        )
        assert is_valid is True
        assert error is None

    def test_path_within_tv_root(self) -> None:
        """Path within TV root should be valid."""
        is_valid, error = validate_media_path(
            "/tv/comedy/series/episode.mp4", None, "/tv"
        )
        assert is_valid is True
        assert error is None

    def test_path_outside_roots(self) -> None:
        """Path outside configured roots should be invalid."""
        is_valid, error = validate_media_path("/other/path/file.mp4", "/movies", "/tv")
        assert is_valid is False
        assert error is not None
        assert "not within configured root directories" in error

    def test_path_in_movies_when_both_roots_configured(self) -> None:
        """Path in movies root should be valid even when TV root is also configured."""
        is_valid, error = validate_media_path(
            "/movies/sci-fi/film.mp4", "/movies", "/tv"
        )
        assert is_valid is True
        assert error is None

    def test_relative_path_rejected(self) -> None:
        """A relative path must be rejected (server paths must be absolute)."""
        is_valid, error = validate_media_path("../etc/passwd", "/movies", "/tv")
        assert is_valid is False
        assert error is not None
        assert "absolute" in error

    def test_dotdot_escape_rejected(self) -> None:
        """A '..' segment that escapes the root must be rejected."""
        is_valid, error = validate_media_path(
            "/movies/../../etc/passwd", "/movies", "/tv"
        )
        assert is_valid is False
        assert error is not None

    def test_null_byte_rejected(self) -> None:
        """A NUL byte in the path must be rejected."""
        is_valid, error = validate_media_path("/movies/film\x00.mp4", "/movies", "/tv")
        assert is_valid is False
        assert error is not None
        assert "control" in error

    def test_control_char_rejected(self) -> None:
        """A control character in the path must be rejected."""
        is_valid, error = validate_media_path("/movies/film\x1f.mp4", "/movies", "/tv")
        assert is_valid is False
        assert error is not None
        assert "control" in error

    def test_empty_path_rejected(self) -> None:
        """An empty path must be rejected."""
        is_valid, error = validate_media_path("", "/movies", "/tv")
        assert is_valid is False
        assert error is not None

    def test_symlink_escape_rejected(self) -> None:
        """A symlink inside the root pointing outside must be rejected.

        ``os.path.realpath`` resolves the symlink, so the canonical path lands
        outside the root and fails the containment prefix check.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "movies")
            outside = os.path.join(tmp, "secret")
            os.makedirs(root)
            os.makedirs(outside)
            link = os.path.join(root, "escape")
            os.symlink(outside, link)
            is_valid, error = validate_media_path(
                os.path.join(link, "film.mp4"), root, None
            )
            assert is_valid is False
            assert error is not None

    def test_within_root_symlink_allowed(self) -> None:
        """A symlink that stays inside the root is accepted."""
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "movies")
            sub = os.path.join(root, "sub")
            os.makedirs(sub)
            link = os.path.join(root, "link")
            os.symlink(sub, link)
            is_valid, error = validate_media_path(
                os.path.join(link, "film.mp4"), root, None
            )
            assert is_valid is True
            assert error is None


class TestGetMediaType:
    """Tests for get_media_type function."""

    def test_no_roots_returns_unknown(self) -> None:
        """When no roots configured, should return unknown."""
        media_type = get_media_type("/some/path.mp4", None, None)
        assert media_type == "unknown"

    def test_path_in_movies_root(self) -> None:
        """Path in movies root should return movie."""
        media_type = get_media_type("/movies/action/film.mp4", "/movies", None)
        assert media_type == "movie"

    def test_path_in_tv_root(self) -> None:
        """Path in TV root should return tv."""
        media_type = get_media_type("/tv/comedy/series/ep1.mp4", None, "/tv")
        assert media_type == "tv"

    def test_path_not_in_any_root(self) -> None:
        """Path not in any configured root should return unknown."""
        media_type = get_media_type("/other/path.mp4", "/movies", "/tv")
        assert media_type == "unknown"


class TestGenerateOutputPath:
    """Tests for generate_output_path function."""

    def test_same_directory_with_language(self) -> None:
        """When subtitles_same_directory=True, should generate path in same dir."""
        output_path = generate_output_path(
            "/movies/action/film.mp4",
            language_code="en",
            output_format="srt",
            subtitles_same_directory=True,
        )
        assert output_path == "/movies/action/film.en.srt"

    def test_same_directory_without_language(self) -> None:
        """When no language code, should not include it in filename."""
        output_path = generate_output_path(
            "/movies/action/film.mp4",
            language_code=None,
            output_format="srt",
            subtitles_same_directory=True,
        )
        assert output_path == "/movies/action/film.srt"

    def test_same_directory_custom_format(self) -> None:
        """Should use custom format when specified."""
        output_path = generate_output_path(
            "/tv/comedy/ep1.mkv",
            language_code="fr",
            output_format="vtt",
            subtitles_same_directory=True,
        )
        assert output_path == "/tv/comedy/ep1.fr.vtt"

    def test_fallback_to_output_dir(self) -> None:
        """When subtitles_same_directory=False, should use /output fallback."""
        output_path = generate_output_path(
            "/movies/action/film.mp4",
            language_code="en",
            output_format="srt",
            subtitles_same_directory=False,
        )
        assert output_path == "/output/film.en.srt"


class TestNormalizePath:
    """Tests for normalize_path function."""

    def test_normalize_removes_trailing_slash(self) -> None:
        """Should remove trailing slash."""
        assert normalize_path("/path/to/dir/") == "/path/to/dir"

    def test_normalize_removes_double_slash(self) -> None:
        """Should normalize double slashes."""
        assert normalize_path("/path//to///dir") == "/path/to/dir"

    def test_normalize_mixed_slashes(self) -> None:
        """Should handle mixed forward and backward slashes."""
        result = normalize_path("/path/to\\mixed\\dir")
        # On Linux, backslashes are treated as regular characters
        assert "//" not in result


class TestPathIsAbsolute:
    """Tests for path_is_absolute function."""

    def test_absolute_path(self) -> None:
        """Should return True for absolute paths."""
        assert path_is_absolute("/absolute/path") is True

    def test_relative_path(self) -> None:
        """Should return False for relative paths."""
        assert path_is_absolute("relative/path") is False
        assert path_is_absolute("./relative/path") is False


class TestPathsOverlap:
    """Tests for paths_overlap function."""

    def test_parent_child_overlap(self) -> None:
        """Parent and child paths should overlap."""
        assert paths_overlap("/parent", "/parent/child") is True
        assert paths_overlap("/parent/child", "/parent") is True

    def test_same_path_overlap(self) -> None:
        """Same paths should overlap."""
        assert paths_overlap("/same/path", "/same/path") is True

    def test_no_overlap(self) -> None:
        """Different paths should not overlap."""
        assert paths_overlap("/path1", "/path2") is False

    def test_sibling_paths_no_overlap(self) -> None:
        """Sibling paths should not overlap."""
        assert paths_overlap("/parent/child1", "/parent/child2") is False
