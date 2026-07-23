"""Shared fixtures modeling Bazarr's real `/api/series` wire format.

Reverse-engineered against the actual Bazarr source (flask-restx marshal
models in `bazarr/api/series/series.py` and the `postprocess()` helper in
`bazarr/api/utils.py`), not against our own client schema — the previous
fixtures encoded our own (wrong) assumptions about the wire shape, which is
exactly what let the schema mismatch reach production undetected.

Key facts baked in here:
  - ``audio_language`` is marshaled as a JSON array of ``{name, code2, code3}``
    when the DB column is set (possibly empty), and as a dict of all-null
    values when the column is NULL (flask-restx ``fields.Nested`` over
    ``None``) - never a populated dict.
  - Every item key is always present (marshal fills in defaults/nulls);
    only ``path``/``title``/``sonarrSeriesId`` are reliably non-null.
  - ``total`` in the envelope is the *unfiltered* library count, not
    ``len(data)`` - it can be far larger when a ``length`` limit is used.
"""

from typing import Any


def realistic_series_item(**overrides: Any) -> dict[str, Any]:
    """A fully-populated `/api/series` item, exactly as Bazarr marshals it."""
    item: dict[str, Any] = {
        "alternativeTitles": ["Alt Title"],
        "audio_language": [{"name": "English", "code2": "en", "code3": "eng"}],
        "episodeFileCount": 10,
        "ended": True,
        "episodeMissingCount": 2,
        "fanart": "/images/series/1/fanart.jpg",
        "imdbId": "tt1234567",
        "lastAired": "2024-05-01",
        "monitored": True,
        "overview": "Test overview",
        "path": "/tv/Test Series",
        "poster": "/images/series/1/poster.jpg",
        "profileId": 1,
        "seriesType": "standard",
        "sonarrSeriesId": 123,
        "tags": [],
        "title": "Test Series",
        "tvdbId": 456,
        "year": "2024",
    }
    item.update(overrides)
    return item


def realistic_movie_item(**overrides: Any) -> dict[str, Any]:
    """A fully-populated `/api/movies` item, exactly as Bazarr marshals it.

    `audio_language` follows the same wire-shape rules as
    `realistic_series_item` - a JSON array of {name, code2, code3} when the
    DB column is set, a dict-of-nulls when it's NULL.

    `missing_subtitles` and `path` are confirmed present on this endpoint's
    marshal model (`bazarr/api/movies/movies.py`'s `movies_data_model`) -
    the full-sync poller relies on both to derive `has_any_subs` state and
    the authoritative media path without a separate detail call.
    """
    item: dict[str, Any] = {
        "title": "Test Movie",
        "radarrId": 1,
        "path": "/movies/Test Movie (2024)/Test Movie.mkv",
        "subtitles": [],
        "missing_subtitles": [],
        "audio_language": [{"name": "French", "code2": "fr", "code3": "fre"}],
        "sceneName": "Test.Movie.2024.1080p",
        "tags": [],
    }
    item.update(overrides)
    return item


def null_heavy_series_item(**overrides: Any) -> dict[str, Any]:
    """A minimal item: only the non-nullable columns populated.

    Mirrors Bazarr's DB schema where only `path`/`title` are NOT NULL - every
    other column can legitimately be null/empty for a freshly-added series.
    """
    item: dict[str, Any] = {
        "alternativeTitles": [],
        "audio_language": [],
        "episodeFileCount": 0,
        "ended": None,
        "episodeMissingCount": 0,
        "fanart": None,
        "imdbId": None,
        "lastAired": None,
        "monitored": None,
        "overview": None,
        "path": "/tv/Minimal Series",
        "poster": None,
        "profileId": None,
        "seriesType": None,
        "sonarrSeriesId": 2,
        "tags": [],
        "title": "Minimal Series",
        "tvdbId": None,
        "year": None,
    }
    item.update(overrides)
    return item
