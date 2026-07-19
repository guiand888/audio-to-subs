"""Path mapping utilities for Bazarr integration.

Handles translation between Bazarr paths and local worker paths.
"""

import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class PathMap:
    """Path mapping for translating between Bazarr and local paths.

    Maintains an ordered list of (bazarr_prefix, local_prefix) pairs.
    First match wins. Both arguments use os.path.normpath before comparison.
    The suffix after the prefix is preserved verbatim.
    """

    def __init__(self, pairs: list[tuple[str, str]] | None = None) -> None:
        """Initialize PathMap with list of prefix pairs.

        Args:
            pairs: List of (bazarr_prefix, local_prefix) tuples
        """
        self._pairs: list[tuple[str, str]] = []
        self._warned_unmatched: set[str] = set()

        if pairs:
            for bazarr_prefix, local_prefix in pairs:
                self.add_mapping(bazarr_prefix, local_prefix)

    def add_mapping(self, bazarr_prefix: str, local_prefix: str) -> None:
        """Add a mapping pair.

        Args:
            bazarr_prefix: Prefix as seen by Bazarr
            local_prefix: Corresponding local prefix
        """
        norm_bazarr = os.path.normpath(bazarr_prefix)
        norm_local = os.path.normpath(local_prefix)
        self._pairs.append((norm_bazarr, norm_local))

    def translate(self, bazarr_path: str) -> str:
        """Translate a Bazarr path to a local path.

        First matching prefix wins. If no match, return path unchanged.

        Args:
            bazarr_path: Path as returned by Bazarr API

        Returns:
            Translated local path
        """
        if not bazarr_path:
            return bazarr_path

        norm_path = os.path.normpath(bazarr_path)

        for bazarr_prefix, local_prefix in self._pairs:
            # Check if path starts with this prefix
            if norm_path.startswith(bazarr_prefix):
                # Remove prefix and prepend local prefix
                suffix = norm_path[len(bazarr_prefix) :]
                if suffix.startswith(os.sep):
                    suffix = suffix[1:]  # Remove leading separator
                return os.path.normpath(os.path.join(local_prefix, suffix))

        # No match found - warn once per unique prefix
        # Extract the first path component as the prefix to warn about
        path_parts = norm_path.split(os.sep)
        unmatched_prefix = path_parts[0] if path_parts else norm_path

        if unmatched_prefix not in self._warned_unmatched:
            self._warned_unmatched.add(unmatched_prefix)
            logger.info(
                "No path mapping found for Bazarr path prefix: %s. "
                "Path returned unchanged: %s",
                unmatched_prefix,
                norm_path,
            )

        return norm_path

    def translate_back(self, local_path: str) -> str:
        """Translate a local path back to Bazarr's view.

        First matching local prefix wins. If no match, return path unchanged.

        Args:
            local_path: Local path as seen by the worker

        Returns:
            Translated Bazarr path
        """
        if not local_path:
            return local_path

        norm_path = os.path.normpath(local_path)

        for bazarr_prefix, local_prefix in self._pairs:
            # Check if path starts with this local prefix
            if norm_path.startswith(local_prefix):
                # Remove prefix and prepend bazarr prefix
                suffix = norm_path[len(local_prefix) :]
                if suffix.startswith(os.sep):
                    suffix = suffix[1:]  # Remove leading separator
                return os.path.normpath(os.path.join(bazarr_prefix, suffix))

        # No match found
        logger.debug(
            "No reverse path mapping found for local path: %s. "
            "Path returned unchanged.",
            norm_path,
        )
        return norm_path

    def get_mappings(self) -> list[tuple[str, str]]:
        """Get current mappings.

        Returns:
            List of (bazarr_prefix, local_prefix) tuples
        """
        return list(self._pairs)

    def clear(self) -> None:
        """Clear all mappings."""
        self._pairs.clear()
        self._warned_unmatched.clear()

    @classmethod
    def from_settings(cls, path_mappings: list[dict[str, str]]) -> "PathMap":
        """Create PathMap from settings path_mappings list.

        Args:
            path_mappings: List of dicts with 'bazarr_prefix' and 'local_prefix' keys

        Returns:
            Configured PathMap instance
        """
        pairs = []
        for mapping in path_mappings:
            bazarr_prefix = mapping.get("bazarr_prefix", "")
            local_prefix = mapping.get("local_prefix", "")
            if bazarr_prefix and local_prefix:
                pairs.append((bazarr_prefix, local_prefix))
        return cls(pairs)

    def to_settings(self) -> list[dict[str, str]]:
        """Convert to settings path_mappings list.

        Returns:
            List of dicts with 'bazarr_prefix' and 'local_prefix' keys
        """
        return [
            {"bazarr_prefix": bazarr, "local_prefix": local}
            for bazarr, local in self._pairs
        ]

    @classmethod
    async def load_from_db(cls, db: "AsyncSession") -> "PathMap":
        """Load PathMap from the "path_mappings" DB setting.

        Falls back to an empty PathMap (no translation) if the setting is
        missing, empty, or malformed. Import of the Setting model is local
        to avoid a circular import between db.models and this module.
        """
        from sqlalchemy import select

        from audio_to_subs.db.models import Setting

        try:
            result = await db.execute(
                select(Setting.value_json).where(Setting.key == "path_mappings")
            )
            # Selecting a single column returns the scalar value directly,
            # not a Setting row — do not access .value_json on this result.
            value_json = result.scalar_one_or_none()
            if value_json:
                return cls.from_settings(json.loads(value_json))
        except Exception as e:
            logger.warning("Failed to load path_mappings from settings: %s", e)

        return cls()


def translate_path(
    bazarr_path: str,
    path_mappings: list[tuple[str, str]],
) -> str:
    """Convenience function to translate a path using a list of mappings.

    Args:
        bazarr_path: Path from Bazarr
        path_mappings: List of (bazarr_prefix, local_prefix) tuples

    Returns:
        Translated local path
    """
    path_map = PathMap(path_mappings)
    return path_map.translate(bazarr_path)
