"""Pydantic schemas for Bazarr API responses.

Based on Bazarr API research from dev/reference/BAZARR_API_RESEARCH.md
and the actual Bazarr source code in /home/guillaume/Development/bazarr.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class SubtitleLanguage(BaseModel):
    """Language info from Bazarr.

    code2/code3 are declared as plain (non-required) fields.String() in
    Bazarr's own swaggerui models (subtitles_model, subtitles_language_model,
    audio_language_model all share this shape) with no guarantee of a
    non-null value - an unresolved/"Unknown" language track marshals with
    both null. Confirmed against a real Bazarr instance.
    """

    name: str = Field(description="Language name")
    code2: str | None = Field(
        default=None, description="ISO 639-1 two-letter language code"
    )
    code3: str | None = Field(
        default=None, description="ISO 639-2/3 three-letter language code"
    )
    forced: bool = Field(default=False, description="Forced subtitles flag")
    hi: bool = Field(default=False, description="Hearing impaired flag")


class WantedMovie(BaseModel):
    """Movie item from Bazarr wanted list."""

    title: str = Field(description="Movie title")
    missing_subtitles: list[SubtitleLanguage] = Field(
        default_factory=list, description="List of missing subtitle languages"
    )
    radarrId: int = Field(description="Radarr ID for the movie")
    sceneName: str | None = Field(default=None, description="Scene name for the movie")
    tags: list[str] = Field(default_factory=list, description="Movie tags")


class WantedMoviesPage(BaseModel):
    """Response wrapper for movies wanted endpoint."""

    data: list[WantedMovie] = Field(description="List of wanted movies")
    total: int = Field(description="Total count of wanted movies")


class WantedEpisode(BaseModel):
    """Episode item from Bazarr wanted list."""

    seriesTitle: str = Field(description="Series title")
    episode_number: str = Field(description="Episode number in SxxExx format")
    episodeTitle: str = Field(description="Episode title")
    missing_subtitles: list[SubtitleLanguage] = Field(
        default_factory=list, description="List of missing subtitle languages"
    )
    sonarrSeriesId: int = Field(description="Sonarr series ID")
    sonarrEpisodeId: int = Field(description="Sonarr episode ID")
    sceneName: str | None = Field(
        default=None, description="Scene name for the episode"
    )
    tags: list[str] = Field(default_factory=list, description="Episode tags")
    seriesType: str | None = Field(default=None, description="Series type")


class WantedEpisodesPage(BaseModel):
    """Response wrapper for episodes wanted endpoint."""

    data: list[WantedEpisode] = Field(description="List of wanted episodes")
    total: int = Field(description="Total count of wanted episodes")


class Movie(BaseModel):
    """Movie item from Bazarr all movies endpoint."""

    title: str = Field(description="Movie title")
    radarrId: int = Field(description="Radarr ID for the movie")
    subtitles: list[SubtitleLanguage] = Field(
        default_factory=list, description="List of existing subtitles"
    )
    sceneName: str | None = Field(default=None, description="Scene name for the movie")
    tags: list[str] = Field(default_factory=list, description="Movie tags")


class MoviesPage(BaseModel):
    """Response wrapper for all movies endpoint."""

    data: list[Movie] = Field(description="List of all movies")
    total: int = Field(description="Total count of movies")


class Episode(BaseModel):
    """Episode item from Bazarr episodes endpoint.

    `audio_language` and `missing_subtitles` share Bazarr's
    `*_language_model` family with `Series.audio_language` and the wanted
    endpoints - same shape, same null-code gotcha for unresolved tracks.
    Modelled here (rather than relying on pydantic's default ignore-extras)
    so schema validation actually covers them; `_poll_all_episodes` does not
    currently read them, but future callers should not have to discover the
    null-code failure mode the hard way.
    """

    sonarrEpisodeId: int = Field(description="Sonarr episode ID")
    sonarrSeriesId: int = Field(description="Sonarr series ID")
    title: str = Field(description="Episode title")
    subtitles: list[SubtitleLanguage] = Field(
        default_factory=list, description="List of existing subtitles"
    )
    audio_language: list[SubtitleLanguage] = Field(
        default_factory=list,
        description="Audio languages; code2/code3 may be null for unresolved tracks",
    )
    missing_subtitles: list[SubtitleLanguage] = Field(
        default_factory=list, description="List of missing subtitle languages"
    )
    season: int | None = Field(default=None, description="Season number")
    episode: int | None = Field(default=None, description="Episode number")
    path: str | None = Field(default=None, description="File path for the episode")
    sceneName: str | None = Field(
        default=None, description="Scene name for the episode"
    )


class EpisodesPage(BaseModel):
    """Response wrapper for episodes endpoint.

    Unlike /api/series, /api/movies/wanted, and /api/episodes/wanted,
    Bazarr's /api/episodes resource (bazarr/api/episodes/episodes.py)
    marshals with `envelope='data'` only - it never sends a top-level
    `total` at all, so this wrapper carries just `data`. Confirmed against
    a real Bazarr instance.
    """

    data: list[Episode] = Field(description="List of episodes")


class Series(BaseModel):
    """Series item from Bazarr series endpoint."""

    # Only path/title/sonarrSeriesId are reliably non-null in Bazarr's DB
    # (verified against bazarr/app/database.py's TableShows) - every other
    # field below tolerates null/absent since Bazarr's marshal always emits
    # the key but the underlying column can legitimately be empty.
    sonarrSeriesId: int = Field(description="Sonarr series ID")
    title: str = Field(description="Series title")
    path: str = Field(description="File path for the series")
    tvdbId: int | None = Field(default=None, description="TVDB ID")
    imdbId: str | None = Field(default=None, description="IMDB ID")
    monitored: bool = Field(default=False, description="Whether series is monitored")
    profileId: int | None = Field(default=None, description="Languages profile ID")
    seriesType: str | None = Field(default=None, description="Series type")
    tags: list[str] = Field(default_factory=list, description="Series tags")
    alternativeTitles: list[str] = Field(
        default_factory=list, description="Alternative titles"
    )
    ended: bool = Field(default=False, description="Whether series has ended")
    lastAired: str | None = Field(default=None, description="Last aired date")
    fanart: str | None = Field(default=None, description="Fanart URL")
    poster: str | None = Field(default=None, description="Poster URL")
    overview: str | None = Field(default=None, description="Series overview")
    year: str | None = Field(default=None, description="Series year")
    audio_language: list[SubtitleLanguage] = Field(
        default_factory=list,
        description="Audio languages; code2/code3 may be null for unresolved tracks",
    )

    @field_validator("monitored", "ended", mode="before")
    @classmethod
    def _null_bool_is_false(cls, v: Any) -> Any:
        """Bazarr can marshal these DB-nullable booleans as null."""
        return False if v is None else v

    @field_validator("audio_language", mode="before")
    @classmethod
    def _normalize_audio_language(cls, v: Any) -> Any:
        """Bazarr marshals audio_language inconsistently depending on the
        underlying column's state:
          - populated column -> a JSON array of {name, code2, code3}
          - NULL column -> flask-restx's fields.Nested(None) emits a dict
            with every key null, not an array

        Both must normalize to []. Any OTHER dict (i.e. one with real
        values) is not a shape Bazarr actually sends - leave it as-is so
        validation fails and genuine drift surfaces instead of being
        silently accepted.
        """
        if v is None:
            return []
        if isinstance(v, dict) and not any(v.values()):
            return []
        return v


class SeriesPage(BaseModel):
    """Response wrapper for series endpoint."""

    data: list[Series] = Field(description="List of series")
    total: int = Field(description="Total count of series")


class FileEntry(BaseModel):
    """File entry from Bazarr file browser."""

    name: str = Field(description="File/directory name")
    children: bool = Field(
        description="Whether this entry has children (is a directory)"
    )
    path: str = Field(description="Full path to the file/directory")


class FileBrowserResponse(BaseModel):
    """Response wrapper for file browser endpoint."""

    data: list[FileEntry] = Field(description="List of files/directories")


# Unified models for internal use
class BazarrMovie(BaseModel):
    """Normalized movie representation."""

    kind: str = Field(default="movie", description="Item kind")
    title: str = Field(description="Movie title")
    ext_id: int = Field(description="External ID (Radarr ID)")
    scene_name: str | None = Field(default=None, description="Scene name")
    media_path: str | None = Field(default=None, description="Media file path")
    missing_subtitles: list[dict[str, Any]] = Field(
        default_factory=list, description="List of missing subtitles"
    )
    has_any_subs: bool = Field(default=False, description="Has any subtitles")
    tags: list[str] = Field(default_factory=list, description="Tags")


class BazarrEpisode(BaseModel):
    """Normalized episode representation."""

    kind: str = Field(default="episode", description="Item kind")
    series_title: str = Field(description="Series title")
    episode_number: str = Field(description="Episode number in SxxExx format")
    episode_title: str = Field(description="Episode title")
    ext_id: int = Field(description="External ID (Sonarr Episode ID)")
    series_ext_id: int = Field(description="External series ID (Sonarr Series ID)")
    scene_name: str | None = Field(default=None, description="Scene name")
    media_path: str | None = Field(default=None, description="Media file path")
    missing_subtitles: list[dict[str, Any]] = Field(
        default_factory=list, description="List of missing subtitles"
    )
    has_any_subs: bool = Field(default=False, description="Has any subtitles")
    tags: list[str] = Field(default_factory=list, description="Tags")
    series_type: str | None = Field(default=None, description="Series type")
