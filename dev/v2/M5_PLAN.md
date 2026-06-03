# M5 Execution Plan — History + Logs + Settings

## Goal
Deliver feature-complete v2 with History page, Logs page, Settings page, cost display in UI, and Bazarr auto-rescan after job completion.

## Current State Analysis

### Backend (audio_to_subs/)
- ✅ Jobs API exists: `GET /api/jobs`, `POST /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`
- ✅ Logs API exists: `GET /api/jobs/{id}/logs`, `POST /api/jobs/{id}/logs`
- ✅ Settings API exists: `GET /api/settings`, `PATCH /api/settings`, `GET /api/settings/{key}`
- ✅ SSE stream: `/api/jobs/stream` with new/progress/done/cancel events
- ✅ Worker rescan stubs: `_rescan_bazarr_movie` and `_rescan_bazarr_episode` in `worker/runner.py`
- ❌ Missing: `/api/history` endpoint for completed jobs
- ❌ Missing: `/api/logs` endpoint for global/logs across jobs
- ❌ Missing: `/api/jobs/{id}/notify-bazarr` explicit endpoint (worker uses direct Bazarr client)
- ❌ Bazarr client rescan methods are stubs (log warnings but don't call real endpoints)

### Frontend (frontend/)
- ✅ Scaffold: Vite + TS + Tailwind + shadcn/ui
- ✅ Auth: Login page + AuthGate + protected routes
- ✅ Theming: light/dark/auto
- ✅ Pages: `/login`, `/wanted`, `/queue`
- ✅ Layout: sidebar + theme toggle
- ✅ SSE: Global store wired to `/api/jobs/stream`
- ✅ Types: Full TypeScript mirrors in `lib/types.ts`
- ✅ API client: Thin fetch wrapper with credentials
- ❌ Missing: `/history` page
- ❌ Missing: `/logs` page  
- ❌ Missing: `/settings` page
- ❌ ComingSoonPage placeholders exist for all three

### Worker
- ✅ Rescan stubs call `client.rescan_movie()` and `client.rescan_episode()`
- ❌ Bazarr client methods are stubs that log warnings instead of making real API calls

---

## Task Breakdown

### Phase 1: Backend API Endpoints (Parallelizable)

#### 1.1 `/api/history` Endpoint
**File**: `audio_to_subs/api/routes/history.py` (NEW)
**Tasks**:
- Create router with prefix `/api/history`
- `GET /api/history` - List completed jobs (done/failed/cancelled) with pagination
- Include aggregate stats: total cost, total duration, counts by status/language
- Response model: `HistoryResponse` with `jobs: list[JobResponse]` + `stats: HistoryStats`
- Filter by: status (done/failed/cancelled), date range, source, language
- Reuse existing `JobResponse` model from jobs.py
- Add tests: `test_api_history.py`

**Acceptance**:
- `GET /api/history` returns completed jobs with aggregate cost/duration stats
- Filters work correctly
- Pagination works

#### 1.2 `/api/logs` Endpoint  
**File**: `audio_to_subs/api/routes/logs.py` (EXTEND)
**Tasks**:
- Add `GET /api/logs` - List logs across all jobs (or filtered)
- Parameters: limit, offset, level_filter, job_id (optional), since (timestamp)
- Response: `LogsResponse` with `logs: list[LogEntry]` + `total: int`
- Reuse `JobLogResponse` from existing logs.py
- Add tests: extend `test_api_logs.py` (or create new)

**Acceptance**:
- `GET /api/logs` returns paginated logs
- Can filter by job_id, level, date range

#### 1.3 `/api/jobs/{id}/notify-bazarr` Endpoint
**File**: `audio_to_subs/api/routes/jobs.py` (EXTEND)
**Tasks**:
- Add `POST /api/jobs/{id}/notify-bazarr` endpoint
- Triggers Bazarr rescan for the job's source (movie or episode)
- Returns 202 Accepted (best-effort, async)
- Uses existing `_rescan_bazarr_movie` / `_rescan_bazarr_episode` logic
- Requires: BAZARR_URL and BAZARR_API_KEY configured
- Add test: `test_api_jobs_notify_bazarr.py`

**Acceptance**:
- Endpoint callable and returns 202
- Rescan logic works (or logs warning if Bazarr not configured)

#### 1.4 Update Bazarr Client Rescan Methods
**File**: `audio_to_subs/bazarr/client.py` (MODIFY)
**Tasks**:
- Research actual Bazarr rescan API endpoints
- Implement `rescan_movie(radarr_id: int)` with real API call
- Implement `rescan_episode(sonarr_episode_id: int)` with real API call
- Handle errors gracefully (log but don't raise for job completion)
- Add retry logic for transient failures

**Acceptance**:
- Methods make real HTTP calls to Bazarr API
- Errors are logged but don't crash job completion

---

### Phase 2: Frontend Pages (Parallelizable)

#### 2.1 History Page
**File**: `frontend/src/pages/HistoryPage.tsx` (NEW)
**Tasks**:
- Create page at `/history` (replace ComingSoon placeholder)
- Fetch `GET /api/history` on mount
- Display table of completed jobs with columns:
  - Status (with icon from JobStatusIcon)
  - Source + Source Ref
  - Media path (truncated)
  - Language
  - Duration
  - Cost (formatted USD)
  - Created at
  - Actions (view details)
- Show aggregate stats at top: total jobs, total cost, total duration, average cost/job
- Add filters: date range picker, status selector, source selector
- Add pagination controls
- Use existing Table component from shadcn/ui

**Dependencies**:
- `/api/history` endpoint (Phase 1.1)

**Acceptance**:
- Page loads and displays completed jobs
- Aggregate stats shown
- Filters work
- Pagination works

#### 2.2 Logs Page
**File**: `frontend/src/pages/LogsPage.tsx` (NEW)
**Tasks**:
- Create page at `/logs` (replace ComingSoon placeholder)
- Fetch `GET /api/logs` on mount
- Display logs in a scrollable list with:
  - Timestamp
  - Level (color-coded: debug=gray, info=blue, warning=yellow, error=red)
  - Message
  - Job ID (link to job detail if available)
- Add filters: level selector, date range, job_id search
- Auto-refresh every 10 seconds
- Virtualized list for performance (react-window or tanstack-table)
- Use existing shadcn/ui components

**Dependencies**:
- `/api/logs` endpoint (Phase 1.2)

**Acceptance**:
- Page loads and displays logs
- Auto-refresh works
- Filters work
- Color-coding by level

#### 2.3 Settings Page
**File**: `frontend/src/pages/SettingsPage.tsx` (NEW)
**Tasks**:
- Create page at `/settings` (replace ComingSoon placeholder)
- Fetch `GET /api/settings` on mount
- Display form with sections:

  **Mistral Configuration:**
  - Model selector (dropdown with common models: mistral-medium-latest, voxtral-mini-latest, etc.)
  - Audio rate: `mistral_rate_usd_per_minute` (number input, USD per minute)
  - Input token rate: `mistral_input_token_rate_usd` (nullable number)
  - Output token rate: `mistral_output_token_rate_usd` (nullable number)
  - Fallback note: "When Mistral usage data unavailable, uses audio duration x rate"

  **Bazarr Configuration:**
  - Poll interval: `bazarr_poll_interval` (number input, seconds)
  - Track no subs: `bazarr_track_no_subs` (checkbox)

  **Path Mappings:**
  - List of from->to pairs
  - Add/remove mapping rows
  - Default: empty list

  **Default Values:**
  - Default language: `default_language` (text input, e.g., "en")
  - Default output format: `default_output_format` (dropdown: srt, vtt, webvtt, sbv)

- Save button calls `PATCH /api/settings`
- Show save success/error toast
- Form validation (positive numbers for rates, valid language codes)

**Dependencies**:
- `/api/settings` GET/PATCH (already exists)

**Acceptance**:
- Page loads and displays current settings
- Form edits persist on save
- Settings take effect immediately (poll interval, cost rates)

#### 2.4 Update Router
**File**: `frontend/src/routes/router.tsx` (MODIFY)
**Tasks**:
- Replace ComingSoonPage imports with actual page components
- Import HistoryPage, LogsPage, SettingsPage
- Update route definitions to use real components

---

### Phase 3: Cost Display in UI

#### 3.1 Job Detail Cost Display
**File**: `frontend/src/pages/QueuePage.tsx` (MODIFY)
**Tasks**:
- Add cost display to job detail view
- Show `estimated_cost_usd` when available
- Format: "$0.25" or "$0.0025"
- Show cost breakdown if available (duration-based vs token-based)

#### 3.2 History Aggregate Cost
**File**: `frontend/src/pages/HistoryPage.tsx` (MODIFY - part of Phase 2.1)
**Tasks**:
- Calculate and display aggregate cost across all shown jobs
- Show per-language cost breakdown
- Show cost by date range

---

### Phase 4: Worker Bazarr Rescan

#### 4.1 Wire Real Bazarr Rescan
**File**: `audio_to_subs/bazarr/client.py` (MODIFY - part of Phase 1.4)
**Tasks**:
- Implement actual rescan endpoints
- Bazarr rescan API research:
  - Movie: `POST /api/movies/{radarrId}/rescan`
  - Episode: `POST /api/episodes/{sonarrEpisodeId}/rescan`
- Add proper error handling and retry

**Acceptance**:
- Rescan methods make real HTTP POST calls to Bazarr
- Log success/failure appropriately

---

## Quality Bar (Definition of Done)

For each sub-task and overall milestone:

- [ ] `pytest` passes (all new tests green)
- [ ] `black --check` clean
- [ ] `ruff check` clean  
- [ ] `mypy --strict` clean
- [ ] New code >= 80% coverage
- [ ] Conventional commit messages with `Signed-off-by: Guillaume Andre <mail@guillaumea.fr>`
- [ ] No new TODO/FIXME without tracking
- [ ] CHANGELOG entry describing what's now possible

---

## Implementation Order

```
M5 IMPLEMENTATION ORDER

  BACKEND PHASE (Can be parallel)
  +-- 1.1 history.py      (API endpoint)
  +-- 1.2 logs.py extend   (API endpoint)
  +-- 1.3 jobs.py extend   (notify-bazarr endpoint)
  +-- 1.4 client.py       (Bazarr rescan methods)

  FRONTEND PHASE (Can be parallel)
  +-- 2.1 HistoryPage.tsx (depends on 1.1)
  +-- 2.2 LogsPage.tsx    (depends on 1.2)
  +-- 2.3 SettingsPage.tsx (depends on existing settings API)
  +-- 2.4 router.tsx      (update imports)

  COST UI PHASE
  +-- 3.1 QueuePage cost display
  +-- 3.2 HistoryPage aggregate cost

  FINAL
  +-- Run full test suite, lint, coverage check
```

---

## File Checklist

### New Files
- [ ] `audio_to_subs/api/routes/history.py`
- [ ] `frontend/src/pages/HistoryPage.tsx`
- [ ] `frontend/src/pages/LogsPage.tsx`
- [ ] `frontend/src/pages/SettingsPage.tsx`
- [ ] `tests/test_api_history.py`

### Modified Files
- [ ] `audio_to_subs/api/routes/logs.py` (add GET /api/logs)
- [ ] `audio_to_subs/api/routes/jobs.py` (add POST /api/jobs/{id}/notify-bazarr)
- [ ] `audio_to_subs/api/app.py` (include history_router)
- [ ] `audio_to_subs/bazarr/client.py` (implement rescan methods)
- [ ] `frontend/src/routes/router.tsx` (replace ComingSoon with real pages)
- [ ] `frontend/src/pages/QueuePage.tsx` (add cost display)
- [ ] `frontend/src/pages/HistoryPage.tsx` (ensure aggregate cost)

---

## Acceptance Checklist (from MILESTONES.md)

From the milestone definition:

- [ ] Complete several jobs of varying lengths/languages; History shows them with correct duration and cost
- [ ] Settings page edits persist and take effect (poll interval honoured on the next tick; cost rates used for new jobs immediately)
- [ ] Logs page surfaces the milestone messages (stage transitions, errors) for each job

Additional technical acceptance:

- [ ] `/api/history` returns completed jobs with aggregate stats
- [ ] `/api/logs` returns paginated logs with filters
- [ ] `/api/jobs/{id}/notify-bazarr` triggers rescan (202 Accepted)
- [ ] Bazarr client rescan methods make real API calls
- [ ] Settings page allows editing all cost-related settings
- [ ] Cost displayed in Queue and History pages
- [ ] All tests pass, lints clean, coverage >= 80%

---

## Commit Strategy

Each logical unit gets its own commit:

1. `feat(api): add /api/history endpoint for completed jobs`
2. `feat(api): add /api/logs global endpoint`
3. `feat(api): add /api/jobs/{id}/notify-bazarr endpoint`
4. `feat(bazarr): implement real rescan API calls in client`
5. `feat(frontend): add History page with cost aggregates`
6. `feat(frontend): add Logs page with filters`
7. `feat(frontend): add Settings page with Mistral pricing`
8. `feat(frontend): display cost in Queue and History pages`
9. `test: add coverage for new API endpoints`
10. `chore: update router to use new pages`

Each commit message format:
```
docs(v2): M5 execution plan

Plan for executing milestone M5 (History + Logs + Settings)

Signed-off-by: Guillaume Andre <mail@guillaumea.fr>
```

---

## Estimated File Touches

| Category | Files | Lines |
|----------|-------|-------|
| New Backend API | 1 new, 2 modified | ~400 |
| New Frontend Pages | 3 new | ~800 |
| Modified Frontend | 2 modified | ~100 |
| Tests | 2-3 new | ~300 |
| Bazarr Client | 1 modified | ~50 |
| **Total** | **~10 files** | **~1650 lines** |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Bazarr rescan endpoints unknown | Research actual API; if not available, log warning (stub OK per milestone) |
| Frontend state management complexity | Use existing patterns (Zustand store, TanStack Query) |
| Cost calculation drift | Use existing `core/cost.py` compute_cost function |
| Cross-origin issues with SSE | Already working in Queue page, reuse pattern |
| Performance with large history | Pagination + server-side filtering |

---

## Next Actions

1. Start with backend API endpoints (parallelizable)
2. Implement frontend pages (parallelizable)
3. Wire up cost display
4. Implement Bazarr rescan
5. Full test pass + lint + coverage
6. Final verification of all acceptance criteria
