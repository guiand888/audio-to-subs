# Queue progress reporting — code review & redesign (M5.8)

**Status**: implemented (M5.8, 2026-07-10). All five root causes addressed; see "Implementation notes" at the bottom for what changed vs. the original design.
**Trigger**: user-reported UI bug — the Queue page (`/queue`) appeared frozen on "Extracting audio from video…" / 10% for a running job, with no live updates unless manually refreshed. Screenshot showed `bazarr_episode #324`, `Auto · SRT`, pinned at 10%.

This is the authoritative detail document for [`MILESTONES.md`](MILESTONES.md)'s M5.8 entry, per the convention set by `REFACTOR.md` (M5.3) and `MISTRAL_USAGE_PROBE.md` (M0.5): the milestone section stays a short summary, this doc carries the full root-cause analysis and design so it survives context compaction.

## Root-cause findings

### 1. Long stages emit zero interior progress — the actual cause of the screenshot

`audio_to_subs/worker/runner.py:257` constructs the pipeline with `verbose_progress=False` ("We use structured callback"). `Pipeline._single_arg_progress_callback()` (`core/pipeline.py:164-177`) returns `None` whenever `verbose_progress` is off, and that `None` is what gets passed as the `progress_callback` into `extract_audio()` / `split_audio()`.

Without a callback, `audio_extractor.py:99-105` skips fetching `total_duration` via ffprobe and never appends `-progress pipe:1` to the ffmpeg invocation — so `core/ffmpeg_utils.py`'s `_parse_ffmpeg_progress()`, which already computes a real time-based percentage from ffmpeg's own progress stream, never runs at all for jobs going through the worker.

Concretely, each of these stages (`core/pipeline.py`) emits exactly **one event at stage-start and one at stage-completion**, nothing in between:

| Stage | Start % | End % | Emitted interior progress |
|---|---|---|---|
| `extract` | 10 | 25 | none — single blocking `ffmpeg` subprocess call |
| `split` | 25 | 30 | none — single blocking `ffmpeg` subprocess call (only runs if audio > `max_audio_length`) |
| `transcribe` | 30 | 75 | **yes** — one event per audio segment (`pipeline.py:638`, `30 + int(45 * (idx / total_segments))`) |
| `generate` | 75 | 100 | none — usually fast enough not to matter |

For a large video, ffmpeg's audio decode (`extract`) alone can dominate the job's wall-clock time. That silence is exactly the frozen "Extracting audio from video… 10%" the user saw — the SSE pipeline itself is not broken, it simply has nothing to send during that window.

### 2. New jobs never appear without a manual refresh

`frontend/src/lib/jobsStore.ts:54-56` — the `"new"` SSE event handler only does:

```ts
case "new":
  return { pendingNewCount: state.pendingNewCount + 1 }
```

Nothing in the frontend reads `pendingNewCount` (confirmed by grep — only test files reference the field). A job created by another actor while the Queue page is mounted (Bazarr auto-scan picking up a new episode, another browser tab or user queuing something) never gets inserted into the Zustand store and never triggers a refetch of `GET /api/jobs` — it only appears after a hard refresh reseeds the store from scratch. This is a second, independent way the page can look "frozen," distinct from finding #1.

### 3. Duplicate SSE delivery for events originating in the API process

`register_observers()` (`api/routes/stream.py:262-272`) is only ever called from `api/app.py`'s `lifespan()`. That means the observer lists in `queue_/events.py` (`_job_stream_observers`, `_global_stream_observers`) are populated **only inside the API process** — they are always empty in the separate worker process (`python -m audio_to_subs.worker`, its own Python process per `docker-compose.yml`'s `entrypoint` override).

- **Worker-originated events** (`progress`, `done`): reach SSE clients through exactly one path — Redis pub/sub, since the observer calls in the worker process are no-ops.
- **API-originated events** (`new` from `POST /api/jobs`, `cancel` from the cancel route): go out through **both** the direct in-process observer call *and* the API process's own Redis-subscriber loopback (the API is itself subscribed to `jobs:global` for every connected SSE client, since `_event_generator` in `stream.py` always spins up a `_redis_listener_coro` regardless of origin). Every `new`/`cancel` event is delivered twice per connected client.

Harmless today because the Zustand reducers are idempotent, but wasteful, and it will double-fire visibly once finding #2 is fixed to actually mutate state on `"new"`.

### 4. No persisted stage

`jobs.progress_percent` / `jobs.progress_message` (`db/models.py:125-126`) are the only persisted progress columns. The pipeline's discrete `stage` (`init` / `extract` / `split` / `transcribe` / `generate` / `done`, `core/pipeline.py:42`) is forwarded live over Redis/SSE but never written to the DB (`worker/progress.py`'s `_update_job_progress`, lines 123-154, only sets `progress_percent` and `progress_message`). A page load or refresh mid-job can reconstruct percent and a free-text message, but has no durable, structured way to know which named step the job is in. This blocks a step-based UI from surviving a refresh — it would only work live, off SSE.

### 5. Percent thresholds are arbitrary, unweighted magic numbers

`core/pipeline.py` hardcodes 10 / 25 / 30 / 75 / 100 as stage boundaries with no timing basis behind the weighting. This contributes to the "imprecise" feel the user described even in the one stage that *does* update live today (`transcribe`, via segment-count-based interpolation) — a stage's allotted percent range has no relationship to how long that stage actually tends to take.

## Proposed design

Direction chosen with the user: **step indicator as the primary signal, with a secondary sub-progress bar inside the current step where real sub-progress data exists.**

```
Step 2 of 4 — Extracting audio
[███████░░░░░░░░░░░░░] 42%

Step 3 of 4 — Transcribing (segment 2/5)
[██████████████░░░░░░] 68%
```

When a step has no sub-progress source (e.g. `generate`), the bar renders indeterminate/pulsing instead of a static frozen number — never claim precision the pipeline doesn't have.

### Backend

- **DB**: add `progress_stage` (nullable text) via a new Alembic migration, next after `0003_add_language_mode_and_audio_language.py`. `ProgressBridge._update_job_progress` (`worker/progress.py`) writes it alongside `progress_percent` / `progress_message`.
- **Step accounting**: compute `step_index` / `step_total` once per job in `Pipeline.process_video`. The pipeline already knows, before the first `split` event, whether splitting will actually occur (`audio_duration_seconds > self.max_audio_length`, `pipeline.py:467`) — so `step_total` is 3 or 4 depending on that, rather than a hardcoded 5 that's wrong for the common case of short-enough audio. Include both fields in `ProgressEvent` (`core/pipeline.py:39-48`), the Redis/SSE payload (`queue_/events.py::publish_progress`), the DB row, `JobResponse` (`api/routes/jobs.py`), and the frontend's `JobResponse` / `LiveJob` / `SseEventData` types (`frontend/src/lib/types.ts`, `frontend/src/lib/jobsStore.ts`).
- **Interior progress for `extract` / `split`**: stop gating ffmpeg's native time-based progress behind `verbose_progress`. Give `extract_audio()` / `split_audio()` a callback that maps ffmpeg's `time_s / total_duration` ratio into each stage's percent sub-range (10→25 for extract, 25→30 for split) and forwards it through `_emit_progress`, independent of the legacy "verbose text log" flag which should stay purely about log verbosity, not about whether percent math happens at all. `transcribe`'s existing per-segment progress needs no change.
- **Collapse duplicate SSE delivery**: remove `register_job_stream_observer` / `register_global_stream_observer` / `_notify_*_observers` and their call sites in `publish_new` / `publish_progress` / `publish_cancel` / `publish_done` (`queue_/events.py`), and drop `register_observers()`'s call from `app.py`'s lifespan. Every SSE-serving process is already subscribed to the relevant Redis channel for each connected client (that's how worker-originated events already work) — routing 100% of delivery through Redis, as `QUEUE.md` already documents as the intended architecture, removes the redundant same-process path instead of maintaining two parallel ones.

### Frontend

- `JobCard` (`frontend/src/pages/QueuePage.tsx`): primary label becomes `Step {step_index} of {step_total} — {stage label}`; keep the existing thin `Progress` bar underneath as the secondary "how far into this step" indicator, driven by the same `percent` field (now continuously updating within `extract` / `split`, not just `transcribe`).
- Fix dead `pendingNewCount`: wire it to `queryClient.invalidateQueries({queryKey: ["jobs"]})` in `QueuePage.tsx`, mirroring the existing terminal-event invalidation already there (`QueuePage.tsx:137`, which does the same for `["wanted"]`).

### Explicitly out of scope

Not proposing a switch to polling as the primary transport. `dev/v2/QUEUE.md` already documents the Redis-down fallback ("rows still update so the user can refresh manually") as an accepted, intentional degradation — that stays as-is. This work only fixes the cases where the *live* path is silent or duplicated while Redis is healthy.

## Acceptance criteria (for the milestone)

- A job whose video takes >30s to decode shows continuously advancing percent during "Extracting audio", not a single jump from 10% straight to 25%.
- Creating a job from another tab/actor while the Queue page is open makes it appear in the list within one SSE round-trip — no manual refresh required.
- Each SSE event is delivered to a connected client exactly once (regression test asserting delivery count per `new` / `cancel` event, covering the API-originated path specifically).
- A hard refresh mid-job shows the correct step index and stage label, not just percent/message, by reading the persisted `progress_stage` column.
- `step_total` reflects whether splitting actually occurred for that job (3 vs 4), not a hardcoded constant.
- Full `pytest`, `black --check`, `ruff check`, `mypy --strict` clean; frontend `vitest` and `tsc --noEmit` clean; new code ≥ 80% coverage — per this repo's standard milestone quality bar.

## Implementation notes (M5.8)

Shipped 2026-07-10. Mapping of each root cause to the change:

1. **Interior progress for `extract`/`split`** — `Pipeline._subprogress_callback()`
   (`core/pipeline.py`) builds a `Callable[[str], None]` that parses ffmpeg's own
   trailing `(XX%)` out of the message and maps it into the stage's percent window
   (10→25 for `extract`, 25→30 for `split`), forwarding through `_emit_progress`.
   It is wired into `extract_audio`/`split_audio` whenever a structured callback is
   set, **independent of `verbose_progress`** (the worker path). The legacy
   `_single_arg_progress_callback` was removed as dead code. `transcribe` already
   emitted per-segment progress and is unchanged.
2. **New jobs appear live** — `QueuePage` now watches `pendingNewCount` from the
   Zustand store and calls `queryClient.invalidateQueries({ queryKey: ["jobs"] })`,
   mirroring the existing terminal-event `["wanted"]` invalidation. The seed effect
   then re-seeds the store from the fresh `GET /api/jobs`. (Note: because
   `ProgressBridge` debounces DB writes to ~1 Hz, a running job's live percent may
   briefly reset to the last persisted value on each new-job invalidation — same
   behaviour as before this change, accepted for the milestone.)
3. **Duplicate SSE delivery** — the in-process observer path
   (`register_job_stream_observer`/`register_global_stream_observer`,
   `_notify_*_observers`, `publish_to_job_stream`/`publish_to_global_stream`,
   `register_observers`) was removed from `queue_/events.py`, `api/routes/stream.py`,
   and `api/app.py`. 100% of SSE delivery now flows through Redis pub/sub exactly as
   `QUEUE.md` documents. Regression test added asserting `new`/`cancel` each arrive
   exactly once on `jobs:global`.
4. **Persisted stage/step** — migration `0004_add_progress_stage` adds
   `progress_stage`, `progress_step_index`, `progress_step_total` (nullable) to
   `jobs`. `ProgressBridge._update_job_progress` writes all three; `JobResponse`
   exposes them; the SSE `progress` payload carries `step_index`/`step_total`.
5. **Percent thresholds (magic numbers)** — left at 10/25/30/75/100; reweighting was
   out of scope per the milestone.

**Step numbering** (decided with the user): `init` is hidden, `done` is terminal, so
`step_total` is 3 (no split) or 4 (split) and `extract = step 1`. Mapping:
`extract→1, [split→2,] transcribe→2|3, generate→3|4`. The frontend `JobCard` renders
`Step {i} of {n} — {label}` as the primary label, with the percent bar as the
in-step indicator; stages without a sub-progress source (`generate`, and any stage
before the first interior update) render an indeterminate (pulsing) bar instead of a
frozen number.
