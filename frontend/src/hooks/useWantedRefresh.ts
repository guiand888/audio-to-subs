// Thin adapter over refreshStore.ts's module-scope store, so WantedPage's
// refresh state lives outside the component and survives navigating away
// and back (the store is fed by the persistent SSE connection mounted once
// in AppLayout - see useJobsStream.ts - not a per-mount EventSource).
//
// This used to own all of that state and an EventSource itself; both were
// torn down on unmount, so navigating away from the Wanted page and back
// lost all progress indication even though the refresh kept running
// server-side. See refreshStore.ts for the actual orchestration logic.

import { useCallback } from "react"
import { startWantedRefresh, useRefreshStore } from "@/lib/refreshStore"
import type { RefreshProgress } from "@/lib/refreshStore"

export type { RefreshProgress }

export interface UseWantedRefreshResult {
  /** Kick off a refresh. No-op if a refresh is already in progress. */
  start: (opts: { item_type: "all" | "movie" | "episode" }) => void
  /** Live progress; renders the bar and toggles the Refresh button. */
  progress: RefreshProgress
  /** The id of the in-flight (or most recent) refresh run, or null. */
  refreshId: string | null
}

export function useWantedRefresh(): UseWantedRefreshResult {
  const refreshId = useRefreshStore((s) => s.refreshId)
  const progress = useRefreshStore((s) => s.progress)

  const start = useCallback(
    (opts: { item_type: "all" | "movie" | "episode" }) => {
      startWantedRefresh(opts)
    },
    [],
  )

  return { start, progress, refreshId }
}
