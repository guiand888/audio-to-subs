"""Tests for Bazarr path mapping utilities."""

from audio_to_subs.bazarr.pathmap import PathMap, translate_path


class TestPathMapBasic:
    """Test basic PathMap functionality."""

    def test_empty_pathmap(self):
        """Test PathMap with no mappings."""
        path_map = PathMap()

        # Should return path unchanged
        result = path_map.translate("/path/to/file.mkv")
        assert result == "/path/to/file.mkv"

        # Empty path
        result = path_map.translate("")
        assert result == ""

        # None path
        result = path_map.translate(None)
        assert result is None

    def test_add_mapping(self):
        """Test adding mappings."""
        path_map = PathMap()
        path_map.add_mapping("/bazarr/movies", "/local/movies")

        assert len(path_map.get_mappings()) == 1

    def test_clear(self):
        """Test clearing mappings."""
        path_map = PathMap([("/bazarr", "/local")])
        assert len(path_map.get_mappings()) == 1

        path_map.clear()
        assert len(path_map.get_mappings()) == 0


class TestPathMapTranslation:
    """Test path translation."""

    def test_simple_translation(self):
        """Test simple path translation."""
        path_map = PathMap([("/bazarr/movies", "/local/movies")])

        result = path_map.translate("/bazarr/movies/Inception.mkv")
        assert result == "/local/movies/Inception.mkv"

    def test_translation_with_nested_paths(self):
        """Test translation with nested paths."""
        path_map = PathMap([("/bazarr/movies", "/local/movies")])

        result = path_map.translate("/bazarr/movies/Action/Inception.mkv")
        assert result == "/local/movies/Action/Inception.mkv"

    def test_first_match_wins(self):
        """Test that first matching prefix wins."""
        path_map = PathMap(
            [
                ("/bazarr/movies", "/local/movies"),
                ("/bazarr", "/other"),
            ]
        )

        result = path_map.translate("/bazarr/movies/Inception.mkv")
        assert result == "/local/movies/Inception.mkv"

    def test_second_match_if_first_no_match(self):
        """Test that second match is used if first doesn't match."""
        path_map = PathMap(
            [
                ("/bazarr/movies", "/local/movies"),
                ("/bazarr/tv", "/local/tv"),
            ]
        )

        result = path_map.translate("/bazarr/tv/Show.mkv")
        assert result == "/local/tv/Show.mkv"

    def test_no_match_passthrough(self):
        """Test passthrough when no prefix matches."""
        path_map = PathMap([("/bazarr/movies", "/local/movies")])

        result = path_map.translate("/other/path/file.mkv")
        assert result == "/other/path/file.mkv"

    def test_normpath_handling(self):
        """Test that normpath is applied to inputs."""
        path_map = PathMap([("/bazarr/movies", "/local/movies")])

        # Path with .. should be normalized
        result = path_map.translate("/bazarr/movies/../movies/Inception.mkv")
        # After normpath, this becomes /bazarr/movies/Inception.mkv
        assert result == "/local/movies/Inception.mkv"

    def test_windows_style_paths(self):
        """Test Windows-style paths (on Unix, they're just strings)."""
        path_map = PathMap([("C:\\bazarr\\movies", "D:\\movies")])

        # On Unix, this will be treated as a regular string
        result = path_map.translate("C:\\bazarr\\movies\\Inception.mkv")
        assert "Inception.mkv" in result


class TestPathMapReverseTranslation:
    """Test reverse path translation."""

    def test_simple_reverse_translation(self):
        """Test simple reverse path translation."""
        path_map = PathMap([("/bazarr/movies", "/local/movies")])

        result = path_map.translate_back("/local/movies/Inception.mkv")
        assert result == "/bazarr/movies/Inception.mkv"

    def test_reverse_no_match(self):
        """Test reverse translation with no match."""
        path_map = PathMap([("/bazarr/movies", "/local/movies")])

        result = path_map.translate_back("/other/path/file.mkv")
        assert result == "/other/path/file.mkv"


class TestPathMapFromSettings:
    """Test PathMap creation from settings."""

    def test_from_settings_empty(self):
        """Test from_settings with empty list."""
        path_map = PathMap.from_settings([])
        assert len(path_map.get_mappings()) == 0

    def test_from_settings_with_mappings(self):
        """Test from_settings with valid mappings."""
        settings = [
            {"bazarr_prefix": "/bazarr/movies", "local_prefix": "/local/movies"},
            {"bazarr_prefix": "/bazarr/tv", "local_prefix": "/local/tv"},
        ]
        path_map = PathMap.from_settings(settings)

        assert len(path_map.get_mappings()) == 2
        result = path_map.translate("/bazarr/movies/Inception.mkv")
        assert result == "/local/movies/Inception.mkv"

    def test_from_settings_missing_keys(self):
        """Test from_settings with missing keys."""
        settings = [
            {"bazarr_prefix": "/bazarr/movies"},  # Missing local_prefix
            {"local_prefix": "/local/movies"},  # Missing bazarr_prefix
        ]
        path_map = PathMap.from_settings(settings)

        # Only valid pairs should be added
        assert len(path_map.get_mappings()) == 0

    def test_to_settings(self):
        """Test conversion to settings format."""
        path_map = PathMap([("/bazarr/movies", "/local/movies")])

        settings = path_map.to_settings()
        assert len(settings) == 1
        assert settings[0]["bazarr_prefix"] == "/bazarr/movies"
        assert settings[0]["local_prefix"] == "/local/movies"


class TestTranslatePathFunction:
    """Test the convenience translate_path function."""

    def test_translate_path(self):
        """Test translate_path function."""
        mappings = [("/bazarr/movies", "/local/movies")]

        result = translate_path("/bazarr/movies/Inception.mkv", mappings)
        assert result == "/local/movies/Inception.mkv"


class TestPathMapWarnings:
    """Test warning behavior."""

    def test_warn_once_per_prefix(self, caplog):
        """Test that warnings are only logged once per unique prefix."""
        import logging

        # Set up logging
        logger = logging.getLogger("audio_to_subs.bazarr.pathmap")
        logger.setLevel(logging.INFO)

        path_map = PathMap()

        # First call should warn
        with caplog.at_level(logging.INFO, logger=logger.name):
            result1 = path_map.translate("/unmatched/path/file1.mkv")
            assert result1 == "/unmatched/path/file1.mkv"

        # Second call with same prefix should not warn again
        with caplog.at_level(logging.INFO, logger=logger.name):
            result2 = path_map.translate("/unmatched/path/file2.mkv")
            assert result2 == "/unmatched/path/file2.mkv"
