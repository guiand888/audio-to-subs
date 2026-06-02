// Zustand store for live job state, fed by the SSE stream at /api/jobs/stream.
// The store is seeded from GET /api/jobs on page mount and kept fresh via SSE events.
//
// NOTE: The backend emits unnamed SSE `message` events (not named events like
// "progress" / "done"). The JSON payload carries the event type in the `event` field.

import { create } from "zustand"
import type { JobResponse, SseEventData } from "./types"

export interface LiveJob {
  id: string
  status: string
  percent: number
  stage: string
  message: string
  // fields seeded from the GET /api/jobs response
  source: string
  source_ref: string | null
  media_path: string
  language_code: string | null
  output_format: string
  created_at: string
  started_at: string | null
  cancel_requested: boolean
}

interface JobsState {
  jobs: Record<string, LiveJob>
  // increments on every "new" SSE event so components can trigger a refetch
  pendingNewCount: number
  // set to the job_id whenever a terminal event (done/cancel) arrives
  lastTerminalJobId: string | null

  apply: (data: SseEventData) => void
  seed: (jobs: JobResponse[]) => void
  remove: (jobId: string) => void
}

export const useJobsStore = create<JobsState>()((set) => ({
  jobs: {},
  pendingNewCount: 0,
  lastTerminalJobId: null,

  apply: (data) =>
    set((state) => {
      const jobs = { ...state.jobs }

      switch (data.event) {
        case "new":
          return { pendingNewCount: state.pendingNewCount + 1 }

        case "progress":
          if (jobs[data.job_id]) {
            jobs[data.job_id] = {
              ...jobs[data.job_id],
              status: "running",
              percent: data.percent,
              stage: data.stage,
              message: data.message,
            }
          }
          return { jobs }

        case "cancel":
          if (jobs[data.job_id]) {
            jobs[data.job_id] = {
              ...jobs[data.job_id],
              status: "cancelled",
            }
          }
          return { jobs, lastTerminalJobId: data.job_id }

        case "done":
          if (jobs[data.job_id]) {
            jobs[data.job_id] = {
              ...jobs[data.job_id],
              status: data.status,
              percent: 100,
            }
          }
          return { jobs, lastTerminalJobId: data.job_id }

        default:
          return {}
      }
    }),

  seed: (apiJobs) =>
    set(() => {
      const jobs: Record<string, LiveJob> = {}
      for (const j of apiJobs) {
        if (j.status === "queued" || j.status === "running") {
          jobs[j.id] = {
            id: j.id,
            status: j.status,
            percent: j.progress_percent,
            stage: j.progress_message ?? "",
            message: j.progress_message ?? "",
            source: j.source,
            source_ref: j.source_ref,
            media_path: j.media_path,
            language_code: j.language_code,
            output_format: j.output_format,
            created_at: j.created_at,
            started_at: j.started_at,
            cancel_requested: j.cancel_requested,
          }
        }
      }
      return { jobs }
    }),

  remove: (jobId) =>
    set((state) => {
      const jobs = { ...state.jobs }
      delete jobs[jobId]
      return { jobs }
    }),
}))
