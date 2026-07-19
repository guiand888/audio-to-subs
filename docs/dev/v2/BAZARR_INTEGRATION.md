# Bazarr Integration

## Configuration

Read from env vars: `BAZARR_URL`, `BAZARR_API_KEY` or `BAZARR_API_KEY_FILE`, `PATH_MAPPINGS_JSON`. Editable at runtime via Settings page.

## Client

`audio_to_subs/bazarr/client.py` with async httpx client. All methods return Pydantic v2 models. Auth via `X-API-Key` header.

## Polling

`audio_to_subs/bazarr/poller.py` runs as asyncio task in FastAPI lifespan. Polls `/api/movies/wanted` + `/api/episodes/wanted` every N minutes (configurable). Results upserted into `bazarr_cache`.

When `bazarr_track_no_subs=True`: also polls all movies and episodes, includes items with no subtitles in any language.

## Path Mapping

`audio_to_subs/bazarr/pathmap.py` - ordered list of `(bazarr_prefix, local_prefix)` pairs. First match wins. Used when enqueuing jobs to resolve `media_path`.

Fixed in M5.6.1: Path resolution from detail endpoints now works correctly.

## Wanted Endpoint

`GET /api/wanted` reads from `bazarr_cache` only - never from Bazarr directly. UI stays snappy, Bazarr outages invisible to Wanted page.

## After Completion

Worker calls `rescan_movie(radarr_id)` or `rescan_episode(sonarr_episode_id)` on success. Uses real Bazarr API endpoints (implemented in M5).

## bazarr_track_no_subs Setting

- **OFF**: Wanted list only includes items from Bazarr's wanted endpoints (missing configured language subtitles)
- **ON**: Additionally polls ALL movies and episodes, includes items with `subtitles == []` (completely no subtitles)