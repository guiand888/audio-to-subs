// Zustand store for the Wanted-list Bazarr refresh lifecycle, fed by the
// SAME persistent SSE connection as jobsStore (mounted once in AppLayout via
// useJobsStream - see useJobsStream.ts). Module-scope, so it survives page
// navigation: a refresh started on the Wanted page keeps updating even while
// the user is on another page, and WantedPage shows live state immediately
// on remount instead of resetting to idle.
//
// This replaces the old per-mount useWantedRefresh design, which owned its
// own EventSource and React state local to WantedPage - both were torn down
// on unmount, losing all progress indication on navigation.
//
//   1. startWantedRefresh() POSTs /api/wanted/refresh and arms a watchdog.
//      No stream_ready handshake is needed before POSTing: unlike the old
//      per-refresh EventSource, the persistent AppLayout connection has
//      already been subscribed since app load, so the Redis-pub/sub-has-no-
//      backlog race that handshake guarded against doesn't apply here.
//   2. handleRefreshSseEvent() is called by useJobsStream for every SSE
//      frame (alongside useJobsStore.apply) and drives progress/finalize.
//   3. Watchdog: if no refresh_progress arrives within WATCHDOG_TIMEOUT_MS,
//      GET /api/wanted/refresh/{id} once. If the persisted state is
//      terminal, finalize from it; otherwise surface an error and reset.

import { toast } from "sonner"
import { api, ApiError } from "./api"
import { queryClient } from "./queryClient"
import type {
  SseEventData,
  WantedRefreshStatusResponse,
  WantedRefreshResponse,
} from "./types"
import { create } from "zustand"

export interface RefreshProgress {
  active: boolean
  processed: number
  total: number | null
  percent: number
  stage: string
  status: "started" | "completed" | "failed" | null
  error: string | null
}

export const IDLE: RefreshProgress = {
  active: false,
  processed: 0,
  total: null,
  percent: 0,
  stage: "",
  status: null,
  error: null,
}

// If no refresh_progress arrives within this window after the POST, assume
// the SSE delivery path is broken (connection dropped, browser asleep) and
// try to recover via the persisted-state GET endpoint.
const WATCHDOG_TIMEOUT_MS = 30_000

// A non-terminal recovery snapshot doesn't necessarily mean the connection
// is dead - a legitimately slow backend stage (e.g. a large library) can go
// quiet for a watchdog cycle or two without the refresh actually being
// stuck. The first check only establishes a baseline (nothing to compare
// against yet), so give up after this many further consecutive checks show
// zero measurable progress beyond that baseline - a total of
// WATCHDOG_TIMEOUT_MS * (this + 1) before surfacing an error, e.g. 90s.
const MAX_STALLED_WATCHDOG_CHECKS = 2

// How long to leave the bar in its terminal state before resetting to idle.
const FINALIZE_RESET_MS = 3_000

interface RefreshState {
  refreshId: string | null
  progress: RefreshProgress
}

export const useRefreshStore = create<RefreshState>()(() => ({
  refreshId: null,
  progress: IDLE,
}))

function generateRefreshId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID()
  }
  // jsdom (vitest) and very old browsers fall back to a manual RFC-4122 v4.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === "x" ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

// ── Per-run orchestration state ──────────────────────────────────────────
// Module-scope (not React refs/closures): must survive whatever component
// happened to call startWantedRefresh unmounting mid-run. Exactly one run
// is ever in flight at a time (start() no-ops while active), so a single
// set of module-level handles is sufficient - no need to key these by id.
let finalized = false
let watchdog: ReturnType<typeof setTimeout> | null = null
let finalizeTimeout: ReturnType<typeof setTimeout> | null = null
let lastWatchdogProcessed: number | null = null
let stalledWatchdogChecks = 0

function clearTimers(): void {
  if (watchdog) {
    clearTimeout(watchdog)
    watchdog = null
  }
  if (finalizeTimeout) {
    clearTimeout(finalizeTimeout)
    finalizeTimeout = null
  }
}

function resetToIdle(): void {
  clearTimers()
  useRefreshStore.setState({ refreshId: null, progress: IDLE })
}

function setProgress(
  updater: RefreshProgress | ((p: RefreshProgress) => RefreshProgress),
): void {
  useRefreshStore.setState((state) => ({
    progress:
      typeof updater === "function" ? updater(state.progress) : updater,
  }))
}

// ── Finalize: surface terminal status, refetch table, reset later ───────
function finalize(
  status: "completed" | "failed",
  error: string | null,
  processed: number,
): void {
  if (finalized) return
  finalized = true
  clearTimers()

  setProgress((p) => ({
    ...p,
    active: true,
    status,
    error,
    // refresh_done carries the authoritative final count - the last
    // (throttled) refresh_progress may have been emitted before the
    // final few items were processed.
    processed: status === "completed" ? processed : p.processed,
    percent: status === "completed" ? 100 : p.percent,
  }))

  // The cache was written by the background task; refetch so the table
  // picks up the new data. This is the *only* correct moment to
  // invalidate (the bg task is done writing).
  void queryClient.invalidateQueries({ queryKey: ["wanted"] })

  if (status === "completed") {
    toast.success(`Refreshed ${processed} items`)
  } else {
    toast.error(error || "Failed to refresh wanted list")
  }

  finalizeTimeout = setTimeout(resetToIdle, FINALIZE_RESET_MS)
}

// ── Watchdog: no progress in 30s -> try persisted-state recovery ────────
function armWatchdog(id: string): void {
  if (watchdog) clearTimeout(watchdog)
  watchdog = setTimeout(async () => {
    if (finalized) return
    try {
      const snapshot = await api.get<WantedRefreshStatusResponse>(
        `/api/wanted/refresh/${id}`,
      )
      if (finalized) return
      if (snapshot.status === "completed" || snapshot.status === "failed") {
        finalize(
          snapshot.status,
          snapshot.error,
          snapshot.movies_processed + snapshot.episodes_processed,
        )
        return
      }

      // Still "started": the backend snapshot's own processed count tells
      // us whether it's genuinely alive (a slow stage, e.g. a large
      // library's episode sync) or actually stuck. Only the latter should
      // give up on the user.
      if (
        lastWatchdogProcessed === null ||
        snapshot.processed > lastWatchdogProcessed
      ) {
        lastWatchdogProcessed = snapshot.processed
        stalledWatchdogChecks = 0
        setProgress({
          active: true,
          processed: snapshot.processed,
          total: snapshot.total,
          percent: snapshot.percent,
          stage: snapshot.stage,
          status: "started",
          error: null,
        })
        armWatchdog(id)
        return
      }

      stalledWatchdogChecks += 1
      if (stalledWatchdogChecks < MAX_STALLED_WATCHDOG_CHECKS) {
        armWatchdog(id)
        return
      }

      // No progress across several consecutive checks - the connection
      // (or the refresh itself) is genuinely dead. Reset so the user can
      // retry rather than hang forever.
      toast.error("Refresh status unknown, please retry")
      resetToIdle()
    } catch {
      if (finalized) return
      toast.error("Refresh status unknown, please retry")
      resetToIdle()
    }
  }, WATCHDOG_TIMEOUT_MS)
}

/** Kick off a refresh. No-op if a refresh is already in progress. */
export function startWantedRefresh(opts: {
  item_type: "all" | "movie" | "episode"
}): void {
  if (useRefreshStore.getState().progress.active) return

  clearTimers()
  finalized = false
  lastWatchdogProcessed = null
  stalledWatchdogChecks = 0

  const id = generateRefreshId()
  useRefreshStore.setState({
    refreshId: id,
    progress: {
      active: true,
      processed: 0,
      total: null,
      percent: 0,
      stage: "starting",
      status: "started",
      error: null,
    },
  })

  api
    .post<WantedRefreshResponse>("/api/wanted/refresh", {
      item_type: opts.item_type,
      refresh_id: id,
    })
    .then((resp) => {
      if (finalized) return
      if (resp.status === "failed") {
        finalize("failed", resp.error, 0)
        return
      }
      // status === "started": progress will stream over the persistent SSE
      // connection. Arm the watchdog in case delivery breaks.
      armWatchdog(id)
    })
    .catch((err: unknown) => {
      if (finalized) return
      const msg =
        err instanceof ApiError
          ? `Failed to refresh wanted list: ${err.detail}`
          : "Failed to refresh wanted list: unknown error"
      finalize("failed", msg, 0)
    })
}

/** Called by useJobsStream for every SSE frame, alongside useJobsStore.apply. */
export function handleRefreshSseEvent(data: SseEventData): void {
  const { refreshId } = useRefreshStore.getState()
  if (refreshId === null) return

  // Ignore refresh events for other ids (concurrent tabs, a previous run).
  if (
    (data.event === "refresh_progress" || data.event === "refresh_done") &&
    data.refresh_id !== refreshId
  ) {
    return
  }

  if (data.event === "refresh_progress") {
    if (watchdog) clearTimeout(watchdog)
    setProgress({
      active: true,
      processed: data.processed,
      total: data.total,
      percent: data.percent,
      stage: data.stage,
      status: "started",
      error: null,
    })
    armWatchdog(refreshId)
  } else if (data.event === "refresh_done") {
    const total = (data.movies_processed ?? 0) + (data.episodes_processed ?? 0)
    finalize(data.status, data.error ?? null, total)
  }
}
