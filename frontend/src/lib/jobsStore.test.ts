import { describe, it, expect, beforeEach } from "vitest"
import { useJobsStore } from "./jobsStore"
import type { JobResponse, SseEventData } from "./types"

// Mock job data
const MOCK_JOB: JobResponse = {
  id: "job-1",
  status: "queued",
  progress_percent: 0,
  progress_message: null,
  source: "bazarr_movie",
  source_ref: "123",
  media_path: "/path/to/file.mp4",
  language_code: "en",
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

const MOCK_JOB_2: JobResponse = {
  ...MOCK_JOB,
  id: "job-2",
  source_ref: "456",
}

describe("jobsStore", () => {
  beforeEach(() => {
    // Reset the store before each test
    const { getState } = useJobsStore
    getState().jobs
    // Force reset by creating a fresh state
    useJobsStore.setState({
      jobs: {},
      pendingNewCount: 0,
      lastTerminalJobId: null,
    })
  })

  describe("seed()", () => {
    it("initializes jobs from API response", () => {
      const store = useJobsStore.getState()
      store.seed([MOCK_JOB, MOCK_JOB_2])

      const jobs = useJobsStore.getState().jobs
      expect(Object.keys(jobs)).toHaveLength(2)
      expect(jobs["job-1"]).toBeDefined()
      expect(jobs["job-2"]).toBeDefined()
      expect(jobs["job-1"].status).toBe("queued")
      expect(jobs["job-1"].source_ref).toBe("123")
    })

    it("maps JobResponse fields to LiveJob correctly", () => {
      const store = useJobsStore.getState()
      store.seed([MOCK_JOB])

      const job = useJobsStore.getState().jobs["job-1"]
      expect(job.id).toBe("job-1")
      expect(job.status).toBe("queued")
      expect(job.percent).toBe(0)
      expect(job.stage).toBe("")
      expect(job.message).toBe("")
      expect(job.media_path).toBe("/path/to/file.mp4")
      expect(job.language_code).toBe("en")
      expect(job.output_format).toBe("srt")
      expect(job.audio_duration_seconds).toBeNull()
      expect(job.estimated_cost_usd).toBeNull()
    })

    it("replaces previous jobs when seeding", () => {
      const store = useJobsStore.getState()
      store.seed([MOCK_JOB])
      expect(Object.keys(useJobsStore.getState().jobs)).toHaveLength(1)

      store.seed([MOCK_JOB_2])
      expect(Object.keys(useJobsStore.getState().jobs)).toHaveLength(1)
      expect(useJobsStore.getState().jobs["job-2"]).toBeDefined()
      expect(useJobsStore.getState().jobs["job-1"]).toBeUndefined()
    })
  })

  describe("apply() - progress event", () => {
    beforeEach(() => {
      useJobsStore.getState().seed([MOCK_JOB])
    })

    it("updates job to running state with progress", () => {
      const event: SseEventData = {
        event: "progress",
        job_id: "job-1",
        percent: 50,
        stage: "transcribing",
        message: "Processing audio",
      }

      useJobsStore.getState().apply(event)

      const job = useJobsStore.getState().jobs["job-1"]
      expect(job.status).toBe("running")
      expect(job.percent).toBe(50)
      expect(job.stage).toBe("transcribing")
      expect(job.message).toBe("Processing audio")
    })

    it("ignores progress events for non-existent jobs", () => {
      const event: SseEventData = {
        event: "progress",
        job_id: "non-existent",
        percent: 50,
        stage: "transcribing",
        message: "Processing",
      }

      useJobsStore.getState().apply(event)

      // Should not crash, and non-existent job shouldn't be added
      expect(useJobsStore.getState().jobs["non-existent"]).toBeUndefined()
    })
  })

  describe("apply() - done event", () => {
    beforeEach(() => {
      useJobsStore.getState().seed([MOCK_JOB])
    })

    it("marks job as done and sets lastTerminalJobId", () => {
      const event: SseEventData = {
        event: "done",
        job_id: "job-1",
        status: "done",
      }

      useJobsStore.getState().apply(event)

      const job = useJobsStore.getState().jobs["job-1"]
      expect(job.status).toBe("done")
      expect(job.percent).toBe(100)
      expect(useJobsStore.getState().lastTerminalJobId).toBe("job-1")
    })

    it("handles failed job status", () => {
      const event: SseEventData = {
        event: "done",
        job_id: "job-1",
        status: "failed",
      }

      useJobsStore.getState().apply(event)

      const job = useJobsStore.getState().jobs["job-1"]
      expect(job.status).toBe("failed")
      expect(useJobsStore.getState().lastTerminalJobId).toBe("job-1")
    })
  })

  describe("apply() - cancel event", () => {
    beforeEach(() => {
      useJobsStore.getState().seed([MOCK_JOB])
    })

    it("marks job as cancelled and sets lastTerminalJobId", () => {
      const event: SseEventData = {
        event: "cancel",
        job_id: "job-1",
      }

      useJobsStore.getState().apply(event)

      const job = useJobsStore.getState().jobs["job-1"]
      expect(job.status).toBe("cancelled")
      expect(useJobsStore.getState().lastTerminalJobId).toBe("job-1")
    })
  })

  describe("apply() - new event", () => {
    it("increments pendingNewCount", () => {
      const event: SseEventData = {
        event: "new",
        job_id: "job-new",
      }

      expect(useJobsStore.getState().pendingNewCount).toBe(0)
      useJobsStore.getState().apply(event)
      expect(useJobsStore.getState().pendingNewCount).toBe(1)

      useJobsStore.getState().apply(event)
      expect(useJobsStore.getState().pendingNewCount).toBe(2)
    })
  })

  describe("remove()", () => {
    beforeEach(() => {
      useJobsStore.getState().seed([MOCK_JOB, MOCK_JOB_2])
    })

    it("removes job by ID", () => {
      expect(Object.keys(useJobsStore.getState().jobs)).toHaveLength(2)

      useJobsStore.getState().remove("job-1")

      const jobs = useJobsStore.getState().jobs
      expect(Object.keys(jobs)).toHaveLength(1)
      expect(jobs["job-1"]).toBeUndefined()
      expect(jobs["job-2"]).toBeDefined()
    })

    it("handles removal of non-existent job gracefully", () => {
      useJobsStore.getState().remove("non-existent")
      // Should not crash
      expect(Object.keys(useJobsStore.getState().jobs)).toHaveLength(2)
    })
  })

  describe("State transitions", () => {
    beforeEach(() => {
      useJobsStore.getState().seed([MOCK_JOB])
    })

    it("transitions job from queued to running to done", () => {
      let job = useJobsStore.getState().jobs["job-1"]
      expect(job.status).toBe("queued")

      // Progress event transitions to running
      useJobsStore.getState().apply({
        event: "progress",
        job_id: "job-1",
        percent: 25,
        stage: "transcribing",
        message: "Processing",
      })

      job = useJobsStore.getState().jobs["job-1"]
      expect(job.status).toBe("running")
      expect(job.percent).toBe(25)

      // Done event transitions to done
      useJobsStore.getState().apply({
        event: "done",
        job_id: "job-1",
        status: "done",
      })

      job = useJobsStore.getState().jobs["job-1"]
      expect(job.status).toBe("done")
      expect(job.percent).toBe(100)
      expect(useJobsStore.getState().lastTerminalJobId).toBe("job-1")
    })
  })

  describe("Multiple jobs", () => {
    beforeEach(() => {
      useJobsStore.getState().seed([MOCK_JOB, MOCK_JOB_2])
    })

    it("maintains independent state for multiple jobs", () => {
      useJobsStore.getState().apply({
        event: "progress",
        job_id: "job-1",
        percent: 50,
        stage: "transcribing",
        message: "Job 1 processing",
      })

      useJobsStore.getState().apply({
        event: "progress",
        job_id: "job-2",
        percent: 75,
        stage: "formatting",
        message: "Job 2 processing",
      })

      const job1 = useJobsStore.getState().jobs["job-1"]
      const job2 = useJobsStore.getState().jobs["job-2"]

      expect(job1.percent).toBe(50)
      expect(job1.stage).toBe("transcribing")
      expect(job2.percent).toBe(75)
      expect(job2.stage).toBe("formatting")
    })

    it("marks one job as terminal without affecting others", () => {
      useJobsStore.getState().apply({
        event: "progress",
        job_id: "job-1",
        percent: 100,
        stage: "done",
        message: "Completed",
      })

      useJobsStore.getState().apply({
        event: "done",
        job_id: "job-1",
        status: "done",
      })

      const job1 = useJobsStore.getState().jobs["job-1"]
      const job2 = useJobsStore.getState().jobs["job-2"]

      expect(job1.status).toBe("done")
      expect(job2.status).toBe("queued")
      expect(useJobsStore.getState().lastTerminalJobId).toBe("job-1")
    })
  })
})
