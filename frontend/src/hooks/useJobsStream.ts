// Mounts a global SSE connection to /api/jobs/stream and pipes events into
// the Zustand jobs store (and the Wanted-refresh store). Must be mounted
// exactly once — done in AppLayout.
//
// IMPORTANT: The backend emits unnamed SSE `message` events (not named events).
// The event type lives inside the JSON payload as the `event` field.
// Using es.addEventListener("progress", ...) would silently never fire.
//
// Wanted-list Bazarr refreshes (stream_ready/refresh_progress/refresh_done)
// ride this SAME connection rather than opening their own - see
// refreshStore.ts for why (it's what lets refresh progress survive
// navigating away from the Wanted page and back).

import { useEffect } from "react"
import { useJobsStore } from "@/lib/jobsStore"
import { handleRefreshSseEvent } from "@/lib/refreshStore"
import type { SseEventData } from "@/lib/types"

export function useJobsStream() {
  const apply = useJobsStore((s) => s.apply)

  useEffect(() => {
    const es = new EventSource("/api/jobs/stream", { withCredentials: true })

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data as string) as SseEventData
        apply(data)
        handleRefreshSseEvent(data)
      } catch {
        // ignore malformed frames
      }
    }

    es.onerror = () => {
      // EventSource will auto-reconnect; no action needed
    }

    return () => {
      es.close()
    }
  }, [apply])
}
