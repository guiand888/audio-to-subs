// Queue page: "Running" and "Queued" sections.
// Seeded from GET /api/jobs; kept live via the Zustand SSE store.
// Cards animate out 1.5s after reaching a terminal state, then disappear.

import { useEffect, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { JobStatusIcon } from "@/components/JobStatusIcon"
import { useJobs, useCancelJob } from "@/hooks/useJobs"
import { useJobsStore } from "@/lib/jobsStore"
import type { LiveJob } from "@/lib/jobsStore"
import { ApiError } from "@/lib/api"

// ── JobCard ───────────────────────────────────────────────────────────────────

interface JobCardProps {
  job: LiveJob
  onCancel: (id: string) => void
  isCancelling: boolean
}

function jobTitle(job: LiveJob): string {
  if (job.source_ref) return `${job.source} #${job.source_ref}`
  // Fall back to the filename
  const parts = job.media_path.replace(/\\/g, "/").split("/")
  return parts[parts.length - 1] ?? job.media_path
}

// Format cost as USD
function formatCost(cost: number | null | undefined): string {
  if (cost === null || cost === undefined) return ""
  if (cost === 0) return "$0.00"
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  if (cost < 1) return `$${cost.toFixed(2)}`
  return `$${cost.toFixed(2)}`
}

// Format duration as human-readable string
function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return ""
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (minutes < 60) return `${minutes}m ${secs}s`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return `${hours}h ${mins}m`
}

function JobCard({ job, onCancel, isCancelling }: JobCardProps) {
  const isTerminal =
    job.status === "done" ||
    job.status === "failed" ||
    job.status === "cancelled"

  return (
    <Card
      className={
        isTerminal ? "opacity-50 transition-opacity duration-700" : undefined
      }
    >
      <CardContent className="pt-4 pb-4 space-y-2">
        {/* Header row */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-medium text-sm truncate">{jobTitle(job)}</p>
            <p className="text-xs text-muted-foreground">
              {job.language_code ?? "—"} · {job.output_format.toUpperCase()}
            </p>
          </div>
          <div className="flex items-center gap-2 flex-none">
            <JobStatusIcon status={job.status} />
            {(job.status === "queued" || job.status === "running") && (
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                title="Cancel job"
                disabled={isCancelling || job.cancel_requested}
                onClick={() => onCancel(job.id)}
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>

        {/* Progress bar (only for running jobs) */}
        {job.status === "running" && (
          <div className="space-y-1">
            <Progress value={job.percent} className="h-1.5" />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span className="truncate">{job.stage || job.message || "Processing…"}</span>
              <span className="flex-none ml-2">{job.percent}%</span>
            </div>
          </div>
        )}

        {/* Cost and duration info (for completed jobs) */}
        {isTerminal && (job.estimated_cost_usd !== null || job.audio_duration_seconds !== null) && (
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            {job.audio_duration_seconds !== null && (
              <span className="flex items-center gap-1">
                <span>Duration: {formatDuration(job.audio_duration_seconds)}</span>
              </span>
            )}
            {job.estimated_cost_usd !== null && (
              <span className="flex items-center gap-1">
                <span>Cost: {formatCost(job.estimated_cost_usd)}</span>
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── QueuePage ─────────────────────────────────────────────────────────────────

export function QueuePage() {
  const queryClient = useQueryClient()
  const { data, refetch } = useJobs({ limit: 200 })
  const cancelJob = useCancelJob()
  const seed = useJobsStore((s) => s.seed)
  const remove = useJobsStore((s) => s.remove)
  const pendingNewCount = useJobsStore((s) => s.pendingNewCount)
  const lastTerminalJobId = useJobsStore((s) => s.lastTerminalJobId)
  const jobs = useJobsStore((s) => s.jobs)

  // Track job IDs we're currently animating out
  const [fadingOut, setFadingOut] = useState<Set<string>>(new Set())

  // Seed the store whenever the API response changes
  useEffect(() => {
    if (data?.jobs) {
      seed(data.jobs)
    }
  }, [data, seed])

  // Refetch whenever a new job is created (via SSE "new" event)
  useEffect(() => {
    if (pendingNewCount > 0) {
      void refetch()
    }
  }, [pendingNewCount, refetch])

  // When a job reaches terminal state: animate out, then remove after delay,
  // and invalidate the history + wanted caches
  useEffect(() => {
    if (!lastTerminalJobId) return
    const jobId = lastTerminalJobId
    setFadingOut((prev) => new Set([...prev, jobId]))
    void queryClient.invalidateQueries({ queryKey: ["wanted"] })
    const timer = setTimeout(() => {
      remove(jobId)
      setFadingOut((prev) => {
        const next = new Set(prev)
        next.delete(jobId)
        return next
      })
    }, 1500)
    return () => clearTimeout(timer)
  }, [lastTerminalJobId, remove, queryClient])

  const handleCancel = (jobId: string) => {
    cancelJob.mutate(jobId, {
      onError: (err) => {
        if (err instanceof ApiError) {
          toast.error(err.detail)
        } else {
          toast.error("Cancel failed")
        }
      },
    })
  }

  const allJobs = Object.values(jobs)
  const running = allJobs.filter((j) => j.status === "running")
  const queued = allJobs.filter((j) => j.status === "queued")
  // Also show recent terminal jobs that are fading out
  const terminal = allJobs.filter(
    (j) =>
      (j.status === "done" || j.status === "failed" || j.status === "cancelled") &&
      fadingOut.has(j.id),
  )

  const isEmpty =
    running.length === 0 && queued.length === 0 && terminal.length === 0

  return (
    <div className="p-4 space-y-6">
      {isEmpty ? (
        <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
          No active jobs.
        </div>
      ) : (
        <>
          {/* Running */}
          {(running.length > 0 || terminal.length > 0) && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                Running
              </h2>
              <div className="space-y-2">
                {[...running, ...terminal].map((job) => (
                  <JobCard
                    key={job.id}
                    job={job}
                    onCancel={handleCancel}
                    isCancelling={cancelJob.isPending}
                  />
                ))}
              </div>
            </section>
          )}

          {/* Queued */}
          {queued.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                Queued
              </h2>
              <div className="space-y-2">
                {queued.map((job) => (
                  <JobCard
                    key={job.id}
                    job={job}
                    onCancel={handleCancel}
                    isCancelling={cancelJob.isPending}
                  />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
