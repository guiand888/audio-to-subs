# README v2

Workflow Example:

1. Bazarr detects that "Movie XYZ" is missing French subtitles
2. Poller fetches this from Bazarr's /api/movies/wanted endpoint
3. Cache updated - "Movie XYZ" appears in Wanted list with missing_subtitles: [{code2: "fr", ...}]
4. User action - User sees "Movie XYZ" in Wanted list and clicks "Transcribe"
5. Job creation - POST /api/jobs with source: "bazarr_movie", source_ref: "123" (Radarr ID)
6. Path resolution - System finds cached item, uses its media_path
7. Queue processing - Worker picks up job and starts transcription
8. Completion - Subtitle file saved, job status updated


What does the toggle "Track Items with No Subtitles" in Settings actually do?

The "Track Items with No Subtitles" toggle (bazarr_track_no_subs setting) expands the Wanted list beyond just items that Bazarr considers "wanted" (missing configured language subtitles).

When OFF (default):

- Wanted list only includes items from Bazarr's /api/movies/wanted and /api/episodes/wanted endpoints
- These are items missing specific configured language subtitles

When ON:

- ADDITIONALLY polls ALL movies and ALL episodes from Bazarr
- Includes items where subtitles == [] (completely no subtitles in any language)
- These items appear in the Wanted list with has_any_subs = False and missing_subtitles = []
- Resource intensive - requires additional API calls per series to get episode lists

Practical Impact:

- OFF: Conservative - only shows items Bazarr thinks need subtitles
- ON: Comprehensive - shows ALL items with no subtitles, even if Bazarr isn't configured to want them
