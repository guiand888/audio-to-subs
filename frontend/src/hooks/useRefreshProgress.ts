// Subscribes to the global SSE stream (/api/jobs/stream) and tracks progress
// for a single Wanted-list refresh, identified by its refresh_id.
//
// The backend emits unnamed SSE `message` events; the event type lives in the
// JSON payload's `event` field, so we parse and discriminate manually (same
// convention as useJobsStream).

import { useEffect, useRef, useState } from "react"
import type { SseEventData } from "@/lib/types"

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

/**
 * Track progress of the refresh identified by `refreshId`.
 *
 * Pass the refresh_id returned by POST /api/wanted/refresh. Returns live
 * progress; when the refresh finishes (refresh_done), `active` stays true
 * briefly (caller resets) but `status` reflects the outcome.
 */
export function useRefreshProgress(refreshId: string | null) {
  const [progress, setProgress] = useState<RefreshProgress>(IDLE)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!refreshId) {
      setProgress(IDLE)
      return
    }

    setProgress({
      active: true,
      processed: 0,
      total: null,
      percent: 0,
      stage: "starting",
      status: "started",
      error: null,
    })

    const es = new EventSource("/api/jobs/stream", { withCredentials: true })
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data as string) as SseEventData
        if (
          (data.event === "refresh_progress" ||
            data.event === "refresh_done") &&
          data.refresh_id !== refreshId
        ) {
          return
        }

        if (data.event === "refresh_progress") {
          setProgress((p) => ({
            ...p,
            active: true,
            processed: data.processed,
            total: data.total,
            percent: data.percent,
            stage: data.stage,
            status: "started",
          }))
        } else if (data.event === "refresh_done") {
          setProgress((p) => ({
            ...p,
            active: true,
            status: data.status,
            error: data.error ?? null,
            // On success, pin the bar full so it reads complete before reset.
            percent: data.status === "completed" ? 100 : p.percent,
          }))
        }
      } catch {
        // ignore malformed frames
      }
    }

    es.onerror = () => {
      // EventSource auto-reconnects; nothing to do.
    }

    return () => {
      es.close()
      esRef.current = null
    }
  }, [refreshId])

  return progress
}
