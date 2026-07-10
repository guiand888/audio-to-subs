import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { HistoryPage } from "./HistoryPage"
import { api } from "@/lib/api"
import type { JobResponse } from "@/lib/types"

const EMPTY_HISTORY = {
  jobs: [],
  stats: {
    total_jobs: 0,
    total_cost_usd: 0,
    total_duration_seconds: 0,
    average_cost_usd: 0,
    average_duration_seconds: 0,
    count_by_status: {},
    count_by_language: {},
    count_by_source: {},
  },
  total: 0,
  limit: 20,
  offset: 0,
}

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(), patch: vi.fn() },
}))

const BASE_JOB: JobResponse = {
  id: "job-1",
  status: "done",
  source: "bazarr_movie",
  source_ref: "1",
  media_path: "/movies/test.mkv",
  output_path: "/movies/test.und.srt",
  language_code: "und",
  language_mode: "auto",
  mistral_detected_language: null,
  needs_language_review: true,
  output_format: "srt",
  priority: 0,
  progress_percent: 100,
  progress_message: null,
  cancel_requested: false,
  worker_id: null,
  audio_duration_seconds: 60,
  mistral_usage_json: null,
  estimated_cost_usd: 0.01,
  error_message: null,
  created_at: "2024-01-01T00:00:00Z",
  started_at: "2024-01-01T00:00:00Z",
  finished_at: "2024-01-01T00:01:00Z",
  updated_at: "2024-01-01T00:01:00Z",
}

function historyWith(jobs: JobResponse[]) {
  return { ...EMPTY_HISTORY, jobs, total: jobs.length }
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe("HistoryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue(EMPTY_HISTORY)
  })

  it("opens the Status filter without throwing Radix empty-value error", async () => {
    const user = userEvent.setup()
    render(<HistoryPage />, { wrapper })

    // The filter form renders immediately (not gated by loading state).
    // Before the fix, Radix throws when it encounters <SelectItem value="">.
    const [statusTrigger] = await screen.findAllByRole("combobox")
    await user.click(statusTrigger)

    // The trigger shows the placeholder and the dropdown item shows the label;
    // both contain this text so use getAllByText.
    expect(screen.getAllByText("All statuses").length).toBeGreaterThan(0)
  })

  it("opens the Source filter without throwing Radix empty-value error", async () => {
    const user = userEvent.setup()
    render(<HistoryPage />, { wrapper })

    const triggers = await screen.findAllByRole("combobox")
    await user.click(triggers[1])

    expect(screen.getAllByText("All sources").length).toBeGreaterThan(0)
  })

  it("renders each job status exactly once", async () => {
    vi.mocked(api.get).mockResolvedValue(historyWith([BASE_JOB]))

    render(<HistoryPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getAllByText("Done")).toHaveLength(1)
    })
  })

  it("shows a review warning and lets the user correct an 'und' auto-mode job", async () => {
    vi.mocked(api.get).mockResolvedValue(historyWith([BASE_JOB]))
    vi.mocked(api.patch).mockResolvedValue({
      ...BASE_JOB,
      language_code: "fr",
      needs_language_review: false,
      output_path: "/movies/test.fr.srt",
    })
    const user = userEvent.setup()

    render(<HistoryPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("und")).toBeInTheDocument()
    })
    await user.click(screen.getByTitle(/couldn't detect a language/i))

    await waitFor(() => {
      expect(screen.getByText("Set language")).toBeInTheDocument()
    })
    const dialog = within(screen.getByRole("dialog"))
    const input = dialog.getByPlaceholderText("e.g. en, fr")
    await user.clear(input)
    await user.type(input, "fr")
    await user.click(dialog.getByText("Save"))

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith("/api/jobs/job-1/language", {
        language_code: "fr",
      })
    })
  })

  it("does not show the review icon for a job that doesn't need review", async () => {
    vi.mocked(api.get).mockResolvedValue(
      historyWith([{ ...BASE_JOB, needs_language_review: false, language_code: "fr" }]),
    )

    render(<HistoryPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("fr")).toBeInTheDocument()
    })
    expect(screen.queryByTitle(/couldn't detect a language/i)).not.toBeInTheDocument()
  })

  it("shows a passive mismatch icon when an explicit pick disagrees with Mistral's detection", async () => {
    vi.mocked(api.get).mockResolvedValue(
      historyWith([
        {
          ...BASE_JOB,
          language_mode: "explicit",
          language_code: "en",
          mistral_detected_language: "fr",
          needs_language_review: false,
        },
      ]),
    )

    render(<HistoryPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("en")).toBeInTheDocument()
    })
    expect(
      screen.getByTitle('Selected "en", but Mistral detected "fr"'),
    ).toBeInTheDocument()
  })

  it("does not show the mismatch icon when the explicit pick matches Mistral's detection", async () => {
    vi.mocked(api.get).mockResolvedValue(
      historyWith([
        {
          ...BASE_JOB,
          language_mode: "explicit",
          language_code: "fr",
          mistral_detected_language: "fr",
          needs_language_review: false,
        },
      ]),
    )

    render(<HistoryPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("fr")).toBeInTheDocument()
    })
    expect(screen.queryByTitle(/Mistral detected/)).not.toBeInTheDocument()
  })
})
