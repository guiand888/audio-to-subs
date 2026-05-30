# v2 — Bazarr integration

Reference: [`../reference/BAZARR_API_RESEARCH.md`](../reference/BAZARR_API_RESEARCH.md). All endpoint shapes, auth, and gaps come from that document.

## Configuration

Read at server startup from env vars (single instance):

- `BAZARR_URL` (e.g., `http://bazarr:6767`)
- `BAZARR_API_KEY` or `BAZARR_API_KEY_FILE` (preferred — points at a docker/podman secret)
- `PATH_MAPPINGS_JSON` — JSON array of `[bazarr_prefix, local_prefix]` pairs

These can be edited at runtime via the Settings page (writes to the `settings` table); the env value seeds the row on first boot only.

## Client surface

`audio_to_subs/bazarr/client.py`:

```python
class BazarrClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 30.0) -> None: ...

    # --- wanted lists (the main listing endpoints) ---
    async def list_wanted_movies(
        self, *, start: int = 0, length: int = -1, radarrid: list[int] | None = None
    ) -> WantedPage: ...

    async def list_wanted_episodes(
        self, *, start: int = 0, length: int = -1, episodeid: list[int] | None = None
    ) -> WantedPage: ...

    # --- full lists (for the "no subs in any language" filter) ---
    async def list_all_movies(self, *, start: int = 0, length: int = -1) -> MoviesPage: ...
    async def list_episodes(self, *, seriesid: int) -> EpisodesPage: ...

    # --- file resolution ---
    async def browse_files(self, *, path: str | None = None) -> list[FileEntry]: ...

    # --- rescan (TBD endpoint) ---
    async def rescan_movie(self, radarr_id: int) -> None: ...
    async def rescan_episode(self, sonarr_episode_id: int) -> None: ...

    # --- internals ---
    async def _get(self, path: str, params: dict | None = None) -> dict: ...
```

- All methods take and return Pydantic v2 models in `bazarr/schemas.py`.
- Auth: every request adds `X-API-Key: {api_key}`.
- HTTP errors: 401 → `BazarrAuthError`; 404 → `BazarrNotFoundError`; 429 → `BazarrRateLimited` (with `Retry-After` if present); 5xx → retry once after 2 s, then `BazarrServerError`.
- Timeouts: `httpx.Timeout(connect=10, read=30)`; configurable later via settings.

### The `rescan_*` TBD

The Bazarr API research doc could not identify a documented "rescan a single item" endpoint. The two `rescan_*` methods are **typed stubs**: they log a `warning` ("Bazarr rescan endpoint not yet wired") and return `None`. They are called centrally (one place in `worker/runner.py` on success, one in `api/routes/jobs.py` for the manual hook) so wiring them up later is a one-file change.

If during implementation the endpoint is discovered, fill it in and remove the warning.

## Polling

`audio_to_subs/bazarr/poller.py` runs as an asyncio task started in the FastAPI lifespan:

```python
async def run_bazarr_poller(app):
    while not app.state.shutdown.is_set():
        interval = await get_setting(app.state.db, "bazarr_poll_interval_seconds", 3600)
        try:
            await poll_once(app)
        except Exception as e:
            log.warning("Bazarr poll failed: %s", e)
        await asyncio.wait_for(app.state.shutdown.wait(), timeout=interval, suppress_timeout=True)
```

`poll_once`:
1. Records `started_at = utcnow()`.
2. Pages through `list_wanted_movies` and `list_wanted_episodes` (length=200 per page until empty).
3. If `bazarr_track_no_subs=True` in settings: also pages `list_all_movies` and, per series, `list_episodes`. Filters items where `subtitles == []`. (This branch is expensive — opt-in.)
4. For each item, upserts into `bazarr_cache` keyed by `"movie:{id}"` / `"episode:{id}"`. Sets `has_any_subs` based on the source data.
5. Deletes rows with `fetched_at < started_at` (= no longer wanted).

Default interval: 3600 s. The API research doc suggests 6 h; for a personal tool 1 h is fine, settable in Settings.

## Path mapping

`audio_to_subs/bazarr/pathmap.py`:

```python
class PathMap:
    def __init__(self, pairs: list[tuple[str, str]]) -> None: ...
    def translate(self, bazarr_path: str) -> str: ...
    def translate_back(self, local_path: str) -> str: ...
```

- Ordered list of `(bazarr_prefix, local_prefix)`. First match wins. Both arguments use `os.path.normpath` before comparison; the suffix after the prefix is preserved verbatim.
- `translate` is used when enqueuing a job (resolve `media_path`).
- `translate_back` is reserved for future calls into Bazarr that need to refer to the file in Bazarr's view.
- If no pair matches, return the path unchanged (warn at `info` level once per unique unmatched prefix).

## Wanted endpoint (UI-facing)

`GET /api/wanted` reads from `bazarr_cache` only — never from Bazarr directly. This is critical:

- Bazarr isn't hit on every page load.
- The UI stays snappy even on a slow Bazarr.
- A Bazarr outage is invisible to the Wanted page (it just shows the last poll's data, with a small "last refreshed at <ts>" hint sourced from `MAX(fetched_at)`).

The endpoint reuses the join with `jobs` to surface `active_job_id` for live UI indicators.

## After a successful transcription

Worker, on `status=done`:
1. Computes the output path (`{video_dir}/{video_stem}.{lang}.{ext}`) — already what `core/subtitle_generator.py` does today.
2. Calls `BazarrClient.rescan_movie(radarr_id)` or `rescan_episode(sonarr_episode_id)` depending on `job.source`.
3. Logs the outcome to `job_logs` (info if it worked, warning if the stub returned).

The poller eventually picks up the change anyway (Bazarr will move the item out of "wanted" once it sees the new file), so even with the rescan TBD, the user experience is correct after one poll cycle.

## Testing

- `tests/test_bazarr_client.py` — `respx`-mocked happy paths (movies wanted, episodes wanted, paging, files), error paths (401, 404, 429 with `Retry-After`, 500-retry-then-fail). Verifies `X-API-Key` header is sent.
- `tests/test_bazarr_pathmap.py` — first-match, suffix preserved, no-match passthrough, reverse mapping.
- `tests/test_bazarr_poller.py` — runs `poll_once` with a stubbed client; asserts upsert behaviour and stale-row deletion. Use an in-memory aiosqlite session.
- `tests/test_api_wanted.py` — seed `bazarr_cache`, hit `/api/wanted` with various filters; assert pagination + `active_job_id` join.

## Future enhancements (not v2)

- Subscribe to webhooks if/when Bazarr adds them (would replace the poller).
- Per-tenant Bazarr config (would move into `users.bazarr_url` / `users.bazarr_api_key`).
- Resolve full paths via Sonarr/Radarr direct API when Bazarr's `sceneName` is insufficient.
