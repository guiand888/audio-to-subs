// Orchestrates the full Wanted-list refresh lifecycle:
//
//   1. Open the global SSE stream (/api/jobs/stream).
//   2. Wait for the backend's stream_ready frame (sent right after
//      pubsub.subscribe completes) so we know events published from here on
//      will actually reach us - Redis pub/sub has no backlog, so without
//      this handshake a fast refresh would publish refresh_done before our
//      subscription existed and we'd hang on "Refreshing..." forever.
//   3. POST /api/wanted/refresh with a client-generated refresh_id (the same
//      id we'll filter SSE events by).
//   4. Drive the progress state machine from refresh_progress / refresh_done
//      frames as they arrive.
//   5. Watchdog: if no refresh_progress arrives within WATCHDOG_TIMEOUT_MS,
//      GET /api/wanted/refresh/{id} once. If the persisted state is
//      terminal, finalize from it; otherwise surface an error and reset.
//
// This hook replaces the older useRefreshProgress hook, which only listened
// (and was vulnerable to the late-subscription race that stream_ready +
// persisted state close together).

import { useCallback, useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { useRefreshWanted } from "@/hooks/useRefreshWanted"
import type {
  SseEventData,
  WantedRefreshStatusResponse,
  WantedRefreshResponse,
} from "@/lib/types"

export interface RefreshProgress {
  active: boolean
  processed: number
  total: number | null
  percent: number
  stage: string
  status: "started" | "completed" | "failed" | null
  error: string | null
}

const IDLE: RefreshProgress = {
  active: false,
  processed: 0,
  total: null,
  percent: 0,
  stage: "",
  status: null,
  error: null,
}

// If stream_ready doesn't arrive within this window, fall back to POSTing
// anyway (without progress streaming). Better than wedging the UI on a
// proxy that swallows SSE.
const READY_TIMEOUT_MS = 5_000

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

export interface UseWantedRefreshResult {
  /** Kick off a refresh. No-op if a refresh is already in progress. */
  start: (opts: { item_type: "all" | "movie" | "episode" }) => void
  /** Live progress; renders the bar and toggles the Refresh button. */
  progress: RefreshProgress
  /** The id of the in-flight (or most recent) refresh run, or null. */
  refreshId: string | null
}

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

export function useWantedRefresh(): UseWantedRefreshResult {
  const queryClient = useQueryClient()
  const refreshMutation = useRefreshWanted()

  const [progress, setProgress] = useState<RefreshProgress>(IDLE)
  const [refreshId, setRefreshId] = useState<string | null>(null)

  // Refs that survive re-renders without triggering them.
  const progressRef = useRef<RefreshProgress>(IDLE)
  const runCleanupRef = useRef<(() => void) | null>(null)

  // Keep progressRef in sync so async callbacks can read current state
  // without capturing stale closures.
  useEffect(() => {
    progressRef.current = progress
  }, [progress])

  // On unmount, tear down whatever run is in flight.
  useEffect(() => {
    return () => {
      runCleanupRef.current?.()
      runCleanupRef.current = null
    }
  }, [])

  const start = useCallback(
    (opts: { item_type: "all" | "movie" | "episode" }) => {
      // Ignore double-clicks while a run is in flight.
      if (progressRef.current.active) return
      // Tear down any half-cleaned-up previous run (defensive).
      runCleanupRef.current?.()
      runCleanupRef.current = null

      const id = generateRefreshId()
      setRefreshId(id)
      setProgress({
        active: true,
        processed: 0,
        total: null,
        percent: 0,
        stage: "connecting",
        status: "started",
        error: null,
      })

      // ── Per-run local state (closed over by the handlers below) ───────
      let finalized = false
      let posted = false
      let eventSource: EventSource | null = null
      let watchdog: ReturnType<typeof setTimeout> | null = null
      let readyTimeout: ReturnType<typeof setTimeout> | null = null
      let finalizeTimeout: ReturnType<typeof setTimeout> | null = null
      // Tracks consecutive watchdog fires with no measurable progress, so a
      // legitimately slow (but alive) backend stage isn't mistaken for a
      // dead connection after a single 30s check.
      let lastWatchdogProcessed: number | null = null
      let stalledWatchdogChecks = 0

      const clearTimers = () => {
        if (watchdog) {
          clearTimeout(watchdog)
          watchdog = null
        }
        if (readyTimeout) {
          clearTimeout(readyTimeout)
          readyTimeout = null
        }
        if (finalizeTimeout) {
          clearTimeout(finalizeTimeout)
          finalizeTimeout = null
        }
      }

      const teardown = () => {
        if (eventSource) {
          eventSource.close()
          eventSource = null
        }
        clearTimers()
        runCleanupRef.current = null
      }
      runCleanupRef.current = teardown

      const resetToIdle = () => {
        teardown()
        setRefreshId(null)
        setProgress(IDLE)
      }

      // ── Finalize: surface terminal status, refetch table, reset later ─
      const finalize = (
        status: "completed" | "failed",
        error: string | null,
        processed: number,
      ) => {
        if (finalized) return
        finalized = true

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

        // The cache was written by the background task; refetch so the
        // table picks up the new data. This is the *only* correct moment
        // to invalidate (the bg task is done writing).
        void queryClient.invalidateQueries({ queryKey: ["wanted"] })

        if (status === "completed") {
          toast.success(`Refreshed ${processed} items`)
        } else {
          toast.error(error || "Failed to refresh wanted list")
        }

        finalizeTimeout = setTimeout(resetToIdle, FINALIZE_RESET_MS)
      }

      // ── Watchdog: no progress in 30s -> try persisted-state recovery ─
      const armWatchdog = () => {
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

            // Still "started": the backend snapshot's own processed count
            // tells us whether it's genuinely alive (a slow stage, e.g. a
            // large library's episode sync) or actually stuck. Only the
            // latter should give up on the user.
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
              armWatchdog()
              return
            }

            stalledWatchdogChecks += 1
            if (stalledWatchdogChecks < MAX_STALLED_WATCHDOG_CHECKS) {
              armWatchdog()
              return
            }

            // No progress across several consecutive checks - the
            // connection (or the refresh itself) is genuinely dead. Reset
            // so the user can retry rather than hang forever.
            toast.error("Refresh status unknown, please retry")
            resetToIdle()
          } catch {
            if (finalized) return
            toast.error("Refresh status unknown, please retry")
            resetToIdle()
          }
        }, WATCHDOG_TIMEOUT_MS)
      }

      // ── POST the refresh request ─────────────────────────────────────
      const doPost = () => {
        if (posted) return
        posted = true
        refreshMutation.mutate(
          { item_type: opts.item_type, refresh_id: id },
          {
            onSuccess: (resp: WantedRefreshResponse) => {
              if (finalized) return
              if (resp.status === "failed") {
                finalize("failed", resp.error, 0)
                return
              }
              // status === "started": progress will stream over SSE.
              // Arm the watchdog in case SSE delivery breaks.
              armWatchdog()
            },
            onError: (err: unknown) => {
              if (finalized) return
              const msg =
                err instanceof ApiError
                  ? `Failed to refresh wanted list: ${err.detail}`
                  : "Failed to refresh wanted list: unknown error"
              finalize("failed", msg, 0)
            },
          },
        )
      }

      // ── Open the SSE stream and wire the message handler ─────────────
      eventSource = new EventSource("/api/jobs/stream", { withCredentials: true })
      eventSource.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data as string) as SseEventData

          // Ignore refresh events for other ids (concurrent tabs, etc).
          if (
            (data.event === "refresh_progress" ||
              data.event === "refresh_done") &&
            data.refresh_id !== id
          ) {
            return
          }

          if (data.event === "stream_ready") {
            // Backend's pubsub.subscribe has completed - safe to POST.
            if (readyTimeout) {
              clearTimeout(readyTimeout)
              readyTimeout = null
            }
            doPost()
          } else if (data.event === "refresh_progress") {
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
            armWatchdog()
          } else if (data.event === "refresh_done") {
            const total =
              (data.movies_processed ?? 0) + (data.episodes_processed ?? 0)
            finalize(data.status, data.error ?? null, total)
          }
        } catch {
          // ignore malformed frames
        }
      }

      eventSource.onerror = () => {
        // EventSource auto-reconnects; the watchdog catches persistent loss.
      }

      // If stream_ready doesn't arrive within READY_TIMEOUT_MS, POST anyway
      // without progress streaming - better than wedging on a hostile proxy.
      readyTimeout = setTimeout(() => {
        if (finalized || posted) return
        doPost()
      }, READY_TIMEOUT_MS)
    },
    [queryClient, refreshMutation],
  )

  return { start, progress, refreshId }
}
