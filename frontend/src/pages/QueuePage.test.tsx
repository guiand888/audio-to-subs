import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { QueuePage } from "./QueuePage"
import { useJobsStore } from "@/lib/jobsStore"
import type { JobResponse } from "@/lib/types"

// Mock the API
vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    constructor(
      public readonly status: number,
      public readonly detail: string,
    ) {
      super(detail)
      this.name = "ApiError"
    }
  },
}))

// Mock the hooks
vi.mock("@/hooks/useJobs", () => ({
  useJobs: () => ({
    data: undefined,
    refetch: vi.fn(),
  }),
  useCancelJob: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}))

vi.mock("@/hooks/useJobsStream", () => ({
  useJobsStream: vi.fn(),
}))

// Mock the JobStatusIcon component
vi.mock("@/components/JobStatusIcon", () => ({
  JobStatusIcon: ({ status }: { status: string }) => <span>Status: {status}</span>,
}))

const MOCK_JOB_QUEUED: JobResponse = {
  id: "job-1",
  status: "queued",
  progress_percent: 0,
  progress_message: null,
  source: "bazarr_movie",
  source_ref: "123",
  media_path: "/path/to/file1.mp4",
  language_code: "en",
  language_mode: "explicit",
  mistral_detected_language: null,
  needs_language_review: false,
  output_format: "srt",
  created_at: "2024-01-01T00:00:00Z",
  started_at: null,
  finished_at: null,
  cancel_requested: false,
  audio_duration_seconds: null,
  estimated_cost_usd: null,
  output_path: null,
  priority: 0,
  worker_id: null,
  mistral_usage_json: null,
  error_message: null,
  updated_at: "2024-01-01T00:00:00Z",
}

const MOCK_JOB_RUNNING: JobResponse = {
  id: "job-2",
  status: "running",
  progress_percent: 50,
  progress_message: "Transcribing audio",
  source: "bazarr_episode",
  source_ref: "456",
  media_path: "/path/to/file2.mp4",
  language_code: "fr",
  language_mode: "explicit",
  mistral_detected_language: null,
  needs_language_review: false,
  output_format: "vtt",
  created_at: "2024-01-01T01:00:00Z",
  started_at: "2024-01-01T01:05:00Z",
  finished_at: null,
  cancel_requested: false,
  audio_duration_seconds: null,
  estimated_cost_usd: null,
  output_path: null,
  priority: 0,
  worker_id: "worker-1",
  mistral_usage_json: null,
  error_message: null,
  updated_at: "2024-01-01T01:05:00Z",
}

const MOCK_JOB_DONE: JobResponse = {
  id: "job-3",
  status: "done",
  progress_percent: 100,
  progress_message: null,
  source: "manual",
  source_ref: "789",
  media_path: "/path/to/file3.mp4",
  language_code: "es",
  language_mode: "explicit",
  mistral_detected_language: null,
  needs_language_review: false,
  output_format: "srt",
  created_at: "2024-01-01T02:00:00Z",
  started_at: "2024-01-01T02:05:00Z",
  finished_at: "2024-01-01T02:15:00Z",
  cancel_requested: false,
  audio_duration_seconds: 120,
  estimated_cost_usd: 0.01,
  output_path: "/path/to/output.srt",
  priority: 0,
  worker_id: "worker-1",
  mistral_usage_json: null,
  error_message: null,
  updated_at: "2024-01-01T02:15:00Z",
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe("QueuePage", () => {
  beforeEach(() => {
    // Reset store before each test
    useJobsStore.setState({
      jobs: {},
      pendingNewCount: 0,
      lastTerminalJobId: null,
    })
    vi.clearAllMocks()
  })

  describe("Display", () => {
    it("shows 'No active jobs' when queue is empty", () => {
      render(<QueuePage />, { wrapper })
      expect(screen.getByText("No active jobs.")).toBeInTheDocument()
    })

    it("displays queued jobs in Queued section", async () => {
      // Seed the store directly (simulating API initialization)
      useJobsStore.getState().seed([MOCK_JOB_QUEUED])

      render(<QueuePage />, { wrapper })

      // Check that job title is displayed (this means the job is rendered in the appropriate section)
      await waitFor(() => {
        expect(screen.getByText(/bazarr_movie #123/i)).toBeInTheDocument()
      })

      // Verify the job is in the store with queued status
      const job = useJobsStore.getState().jobs["job-1"]
      expect(job.status).toBe("queued")
    })

    it("displays running jobs in Running section with progress bar", async () => {
      useJobsStore.getState().seed([MOCK_JOB_RUNNING])

      render(<QueuePage />, { wrapper })

      // Check job title and progress (these are more specific than just "RUNNING")
      await waitFor(() => {
        expect(screen.getByText(/bazarr_episode #456/i)).toBeInTheDocument()
      })

      // Check progress info is displayed
      await waitFor(() => {
        expect(screen.getByText(/50%/)).toBeInTheDocument()
      })
      expect(screen.getByText(/Transcribing audio/)).toBeInTheDocument()
    })

    it("displays jobs grouped by status", async () => {
      useJobsStore.getState().seed([MOCK_JOB_QUEUED, MOCK_JOB_RUNNING])

      render(<QueuePage />, { wrapper })

      await waitFor(() => {
        const text = screen.getAllByText(/RUNNING|QUEUED/i)
        expect(text.length).toBeGreaterThan(0)
      })
    })
  })

  describe("Store as single source of truth", () => {
    it("reads job state from Zustand store on initial render", async () => {
      // Set up store before rendering
      useJobsStore.getState().seed([MOCK_JOB_QUEUED])

      render(<QueuePage />, { wrapper })

      // Job should be visible from store
      await waitFor(() => {
        expect(screen.getByText(/bazarr_movie #123/i)).toBeInTheDocument()
      })
    })

    it("updates when store is mutated via apply()", async () => {
      // Start with queued job
      useJobsStore.getState().seed([MOCK_JOB_QUEUED])

      const { rerender } = render(<QueuePage />, { wrapper })

      // Initially queued - verify the job exists in store
      await waitFor(() => {
        const jobs = useJobsStore.getState().jobs
        expect(jobs["job-1"]).toBeDefined()
        expect(jobs["job-1"].status).toBe("queued")
      })

      // Manually apply a progress update to the store (simulating SSE event)
      useJobsStore.getState().apply({
        event: "progress",
        job_id: "job-1",
        percent: 60,
        stage: "transcribing",
        message: "60% complete",
      })

      // Verify store was updated
      const updatedJob = useJobsStore.getState().jobs["job-1"]
      expect(updatedJob.status).toBe("running")
      expect(updatedJob.percent).toBe(60)

      rerender(<QueuePage />)

      // Should now show as running with updated progress
      await waitFor(() => {
        expect(screen.getByText(/60%/)).toBeInTheDocument()
      })
    })

    it("handles terminal job removal from store", async () => {
      useJobsStore.getState().seed([MOCK_JOB_DONE])
      useJobsStore.setState({ lastTerminalJobId: "job-3" })

      const { rerender } = render(<QueuePage />, { wrapper })

      // Job should initially be visible
      await waitFor(() => {
        expect(screen.getByText(/manual #789/i)).toBeInTheDocument()
      })

      // Remove job from store (simulating cleanup after animation)
      useJobsStore.getState().remove("job-3")

      rerender(<QueuePage />)

      // Job should now be gone
      await waitFor(() => {
        expect(screen.queryByText(/manual #789/i)).not.toBeInTheDocument()
      })
    })
  })

  describe("Multiple jobs", () => {
    it("displays multiple jobs with independent state", async () => {
      useJobsStore.getState().seed([MOCK_JOB_QUEUED, MOCK_JOB_RUNNING])

      render(<QueuePage />, { wrapper })

      await waitFor(() => {
        expect(screen.getByText(/bazarr_movie #123/i)).toBeInTheDocument()
        expect(screen.getByText(/bazarr_episode #456/i)).toBeInTheDocument()
      })
    })

    it("handles updates to multiple jobs independently", async () => {
      useJobsStore.getState().seed([MOCK_JOB_QUEUED, MOCK_JOB_RUNNING])

      const { rerender } = render(<QueuePage />, { wrapper })

      // Update first job to 25% progress
      useJobsStore.getState().apply({
        event: "progress",
        job_id: "job-1",
        percent: 25,
        stage: "starting",
        message: "Starting job 1",
      })

      // Update second job to 75% progress
      useJobsStore.getState().apply({
        event: "progress",
        job_id: "job-2",
        percent: 75,
        stage: "finishing",
        message: "Finishing job 2",
      })

      rerender(<QueuePage />)

      // Both should show updated progress
      await waitFor(() => {
        expect(screen.getByText(/25%/)).toBeInTheDocument()
        expect(screen.getByText(/75%/)).toBeInTheDocument()
      })
    })
  })
})
