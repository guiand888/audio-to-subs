import { describe, it, expect, vi, beforeEach } from "vitest"
import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { WantedPage } from "./WantedPage"

// vi.mock calls are hoisted to the top of the file by vitest, so they must be
// declared once at module scope (not inside individual `it` blocks) - the
// mocked module is shared across all tests in the file, configured per-test
// via vi.mocked(...).mockResolvedValue/mockReturnValue in beforeEach/tests.
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    constructor(
      public readonly status: number,
      public readonly detail: string | Record<string, unknown>,
    ) {
      super(typeof detail === "string" ? detail : JSON.stringify(detail))
      this.name = "ApiError"
    }
    get conflict() {
      return this.status === 409 && typeof this.detail === "object"
        ? (this.detail as Record<string, unknown>)
        : null
    }
  },
}))

const MOCK_WANTED_EMPTY = {
  items: [],
  total: 0,
  last_refreshed_at: null,
}

// POST /api/wanted/refresh only kicks the refresh off; the outcome streams
// back over SSE (see MockEventSource below), matching the async contract
// introduced by the progress-bar refresh (data.status "started"/"failed",
// never "completed" synchronously).
const MOCK_REFRESH_STARTED = {
  status: "started",
  refresh_id: "refresh-1",
  movies_processed: 0,
  episodes_processed: 0,
  error: null,
}

const MOCK_REFRESH_FAILURE = {
  status: "failed",
  refresh_id: "",
  movies_processed: 0,
  episodes_processed: 0,
  error: "Connection failed",
}

// Minimal EventSource stand-in: jsdom has no native EventSource, and
// useRefreshProgress opens one against /api/jobs/stream as soon as a refresh
// starts. Tests that need to observe the post-refresh toast grab the latest
// instance and call `.emit(...)` to simulate a server-sent frame.
class MockEventSource {
  static instances: MockEventSource[] = []
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null

  constructor(public url: string) {
    MockEventSource.instances.push(this)
  }

  close() {}

  static reset() {
    MockEventSource.instances = []
  }

  static latest(): MockEventSource | undefined {
    return MockEventSource.instances[MockEventSource.instances.length - 1]
  }

  emit(data: unknown) {
    // The onmessage handler triggers a React state update (setProgress in
    // useRefreshProgress); wrap it so React batches/flushes it the same way
    // it would a real browser event, avoiding an "update not wrapped in
    // act(...)" warning from these synthetic SSE frames.
    act(() => {
      this.onmessage?.({ data: JSON.stringify(data) })
    })
  }
}

// @ts-expect-error test-only polyfill for an API jsdom doesn't implement
global.EventSource = MockEventSource

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe("WantedPage - Refresh Wanted List", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    MockEventSource.reset()
    vi.mocked(api.get).mockResolvedValue(MOCK_WANTED_EMPTY)
    vi.mocked(api.post).mockResolvedValue(MOCK_REFRESH_STARTED)
  })

  it("renders Refresh button", async () => {
    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Refresh")).toBeInTheDocument()
    })
  })

  it("Refresh button is disabled during refresh", async () => {
    const user = userEvent.setup()
    let resolveRefresh: (value: typeof MOCK_REFRESH_STARTED) => void
    const refreshPromise = new Promise<typeof MOCK_REFRESH_STARTED>((resolve) => {
      resolveRefresh = resolve
    })
    vi.mocked(api.post).mockReturnValue(refreshPromise)

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      const button = screen.getByText("Refresh")
      expect(button).toBeInTheDocument()
      expect(button).not.toBeDisabled()
    })

    // Click the button
    await user.click(screen.getByText("Refresh"))

    // Should show loading state and disable button once the POST resolves
    // and useRefreshProgress picks up the returned refresh_id.
    resolveRefresh!(MOCK_REFRESH_STARTED)
    await waitFor(() => {
      const button = screen.getByText("Refreshing...")
      expect(button).toBeInTheDocument()
      expect(button.closest("button")).toBeDisabled()
    })
  })

  it("shows loading state during refresh", async () => {
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Refresh")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Refresh"))

    // Should show loading state as soon as the started response is picked up
    await waitFor(() => {
      expect(screen.getByText("Refreshing...")).toBeInTheDocument()
    })
  })

  it("shows success notification on completion", async () => {
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Refresh")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Refresh"))

    await waitFor(() => {
      expect(screen.getByText("Refreshing...")).toBeInTheDocument()
    })

    // The backend streams the outcome over SSE; simulate the final frame.
    MockEventSource.latest()!.emit({
      event: "refresh_done",
      refresh_id: "refresh-1",
      status: "completed",
      movies_processed: 5,
      episodes_processed: 3,
    })

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Refreshed 8 items")
    })
  })

  it("shows error notification on a synchronous refresh failure", async () => {
    vi.mocked(api.post).mockResolvedValue(MOCK_REFRESH_FAILURE)
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Refresh")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Refresh"))

    // Wait for the refresh to fail and error to be processed
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled()
    })
  })
})

const MOCK_ITEM_WITH_AUDIO_LANG = {
  id: "movie:1",
  kind: "movie",
  ext_id: 1,
  title: "French Movie",
  media_path: "/movies/french.mkv",
  has_any_subs: false,
  missing_subtitles: [{ code2: "en", name: "English", hi: false, forced: false }],
  audio_language: [{ code2: "fr", code3: "fre", name: "French", hi: false, forced: false }],
  last_polled: "2024-01-01T00:00:00Z",
  active_job_id: null,
  active_job_status: null,
  active_job_progress: null,
}

const MOCK_ITEM_NO_AUDIO_LANG = {
  ...MOCK_ITEM_WITH_AUDIO_LANG,
  id: "movie:2",
  ext_id: 2,
  title: "Unknown Audio Movie",
  audio_language: [],
}

const MOCK_JOB_RESPONSE = {
  id: "job-1",
  status: "queued",
  source: "bazarr_movie",
  source_ref: "1",
  media_path: "/movies/french.mkv",
  output_path: null,
  language_code: null,
  language_mode: "auto",
  mistral_detected_language: null,
  needs_language_review: false,
  output_format: "srt",
  priority: 0,
  progress_percent: 0,
  progress_message: null,
  cancel_requested: false,
  worker_id: null,
  audio_duration_seconds: null,
  mistral_usage_json: null,
  estimated_cost_usd: null,
  error_message: null,
  created_at: "2024-01-01T00:00:00Z",
  started_at: null,
  finished_at: null,
  updated_at: "2024-01-01T00:00:00Z",
}

// The dialog's Language select has no explicit accessible name (its <Label>
// isn't wired via htmlFor), and other comboboxes (language filter, refresh
// scope) can coexist on the page once items are loaded - so scope to the
// dialog and take the first combobox (Language precedes Format in markup).
function dialogLanguageCombobox() {
  return within(screen.getByRole("dialog")).getAllByRole("combobox")[0]
}

describe("WantedPage - Transcribe Dialog language selection", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.post).mockResolvedValue(MOCK_JOB_RESPONSE)
  })

  it("offers Auto-detect and the item's Bazarr audio language, not missing_subtitles", async () => {
    vi.mocked(api.get).mockResolvedValue({
      items: [MOCK_ITEM_WITH_AUDIO_LANG],
      total: 1,
      last_refreshed_at: null,
    })
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("French Movie")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Transcribe"))

    await waitFor(() => {
      expect(dialogLanguageCombobox()).toBeInTheDocument()
    })
    await user.click(dialogLanguageCombobox())

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Auto-detect" })).toBeInTheDocument()
      expect(screen.getByRole("option", { name: "French" })).toBeInTheDocument()
      expect(
        screen.getByRole("option", { name: "Other (manual code)" }),
      ).toBeInTheDocument()
      // The missing-subtitle language ("English") must not appear as a
      // language option - only as the unrelated "Missing" badge.
      expect(screen.queryByRole("option", { name: "English" })).not.toBeInTheDocument()
    })
  })

  it("defaults to the item's audio language when Bazarr reports one", async () => {
    vi.mocked(api.get).mockResolvedValue({
      items: [MOCK_ITEM_WITH_AUDIO_LANG],
      total: 1,
      last_refreshed_at: null,
    })
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("French Movie")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Transcribe"))

    await waitFor(() => {
      expect(dialogLanguageCombobox()).toHaveTextContent("French")
    })
  })

  it("defaults to Auto-detect and offers no language option when Bazarr has none", async () => {
    vi.mocked(api.get).mockResolvedValue({
      items: [MOCK_ITEM_NO_AUDIO_LANG],
      total: 1,
      last_refreshed_at: null,
    })
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Unknown Audio Movie")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Transcribe"))

    await waitFor(() => {
      expect(dialogLanguageCombobox()).toHaveTextContent("Auto-detect")
      expect(screen.queryByText("French")).not.toBeInTheDocument()
    })
  })

  it("submits language_mode 'auto' and a null language_code in Auto-detect mode", async () => {
    vi.mocked(api.get).mockResolvedValue({
      items: [MOCK_ITEM_NO_AUDIO_LANG],
      total: 1,
      last_refreshed_at: null,
    })
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Unknown Audio Movie")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Transcribe"))

    await waitFor(() => {
      expect(screen.getByText("Queue job")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Queue job"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/jobs",
        expect.objectContaining({
          language_mode: "auto",
          language_code: null,
        }),
      )
    })
  })

  it("submits language_mode 'explicit' with the selected Bazarr audio language code", async () => {
    vi.mocked(api.get).mockResolvedValue({
      items: [MOCK_ITEM_WITH_AUDIO_LANG],
      total: 1,
      last_refreshed_at: null,
    })
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("French Movie")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Transcribe"))

    await waitFor(() => {
      expect(screen.getByText("Queue job")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Queue job"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/jobs",
        expect.objectContaining({
          language_mode: "explicit",
          language_code: "fr",
        }),
      )
    })
  })

  it("reveals a manual code input for 'Other' and disables Queue job until filled", async () => {
    vi.mocked(api.get).mockResolvedValue({
      items: [MOCK_ITEM_WITH_AUDIO_LANG],
      total: 1,
      last_refreshed_at: null,
    })
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("French Movie")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Transcribe"))

    await waitFor(() => {
      expect(dialogLanguageCombobox()).toBeInTheDocument()
    })
    await user.click(dialogLanguageCombobox())
    await user.click(screen.getByText("Other (manual code)"))

    const queueButton = screen.getByText("Queue job")
    expect(queueButton.closest("button")).toBeDisabled()

    await user.type(screen.getByPlaceholderText("e.g. en"), "de")
    expect(queueButton.closest("button")).not.toBeDisabled()

    await user.click(queueButton)

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/jobs",
        expect.objectContaining({
          language_mode: "explicit",
          language_code: "de",
        }),
      )
    })
  })
})

describe("WantedPage - Tab Selection Drives Refresh Scope", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    MockEventSource.reset()
    vi.mocked(api.get).mockResolvedValue(MOCK_WANTED_EMPTY)
    vi.mocked(api.post).mockResolvedValue(MOCK_REFRESH_STARTED)
  })

  it("refreshes only movies when the Movies tab is selected", async () => {
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Movies" })).toBeInTheDocument()
    })
    await user.click(screen.getByRole("tab", { name: "Movies" }))
    await user.click(screen.getByText("Refresh"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/wanted/refresh", { item_type: "movie" })
    })
    await waitFor(() => {
      expect(screen.getByText("Refreshing...")).toBeInTheDocument()
    })

    MockEventSource.latest()!.emit({
      event: "refresh_done",
      refresh_id: "refresh-1",
      status: "completed",
      movies_processed: 5,
      episodes_processed: 0,
    })

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Refreshed 5 items")
    })
  })

  it("refreshes only episodes when the Series tab is selected", async () => {
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Series" })).toBeInTheDocument()
    })
    await user.click(screen.getByRole("tab", { name: "Series" }))
    await user.click(screen.getByText("Refresh"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/wanted/refresh", { item_type: "episode" })
    })
    await waitFor(() => {
      expect(screen.getByText("Refreshing...")).toBeInTheDocument()
    })

    MockEventSource.latest()!.emit({
      event: "refresh_done",
      refresh_id: "refresh-1",
      status: "completed",
      movies_processed: 0,
      episodes_processed: 3,
    })

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Refreshed 3 items")
    })
  })

  it("refreshes both when the All tab is selected", async () => {
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Refresh")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Refresh"))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/wanted/refresh", { item_type: "all" })
    })
    await waitFor(() => {
      expect(screen.getByText("Refreshing...")).toBeInTheDocument()
    })

    MockEventSource.latest()!.emit({
      event: "refresh_done",
      refresh_id: "refresh-1",
      status: "completed",
      movies_processed: 5,
      episodes_processed: 3,
    })

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Refreshed 8 items")
    })
  })
})

describe("WantedPage - Transcribe error handling", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue({
      items: [MOCK_ITEM_WITH_AUDIO_LANG],
      total: 1,
      last_refreshed_at: null,
    })
  })

  it("surfaces the server error detail in the toast on a 400", async () => {
    vi.mocked(api.post).mockRejectedValue(
      new ApiError(
        400,
        "No media file path is available for this item from Bazarr. Refresh the wanted list and try again.",
      ),
    )
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("French Movie")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Transcribe"))

    await waitFor(() => {
      expect(screen.getByText("Queue job")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Queue job"))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "No media file path is available for this item from Bazarr. Refresh the wanted list and try again.",
      )
    })
  })

  it("shows the 'already active' message on a 409", async () => {
    vi.mocked(api.post).mockRejectedValue(
      new ApiError(409, "A job for this item is already active"),
    )
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("French Movie")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Transcribe"))

    await waitFor(() => {
      expect(screen.getByText("Queue job")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Queue job"))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("A job for this item is already active")
    })
  })

  it("shows overwrite confirm dialog on subtitle_exists and retries with overwrite", async () => {
    // First attempt collides with an existing subtitle; the second (after
    // confirming) succeeds with overwrite=true.
    vi.mocked(api.post)
      .mockRejectedValueOnce(
        new ApiError(409, {
          code: "subtitle_exists",
          message: "An en subtitle already exists at /movies/foo.en.srt",
          existing_path: "/movies/foo.en.srt",
          language_code: "en",
        }),
      )
      .mockResolvedValueOnce({ id: "new-job", status: "queued" } as never)

    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("French Movie")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Transcribe"))

    await waitFor(() => {
      expect(screen.getByText("Queue job")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Queue job"))

    // Confirm dialog appears instead of an error toast.
    await waitFor(() => {
      expect(screen.getByText("Subtitle already exists")).toBeInTheDocument()
    })
    expect(toast.error).not.toHaveBeenCalled()

    await user.click(screen.getByText("Overwrite and retry"))

    await waitFor(() => {
      expect(api.post).toHaveBeenLastCalledWith(
        "/api/jobs",
        expect.objectContaining({ overwrite: true }),
      )
    })
    expect(toast.success).toHaveBeenCalledWith("Job queued")
  })
})

describe("WantedPage - Default title sort & search", () => {
  const MOCK_TITLE_ITEMS = [
    {
      id: "movie:3",
      kind: "movie",
      ext_id: 3,
      title: "zebra Movie",
      media_path: "/movies/zebra.mkv",
      has_any_subs: false,
      missing_subtitles: [{ code2: "en", name: "English", hi: false, forced: false }],
      audio_language: [{ code2: "en", code3: "eng", name: "English", hi: false, forced: false }],
      last_polled: "2024-01-01T00:00:00Z",
      active_job_id: null,
      active_job_status: null,
      active_job_progress: null,
    },
    {
      id: "movie:1",
      kind: "movie",
      ext_id: 1,
      title: "Alpha Movie",
      media_path: "/movies/alpha.mkv",
      has_any_subs: false,
      missing_subtitles: [{ code2: "en", name: "English", hi: false, forced: false }],
      audio_language: [{ code2: "en", code3: "eng", name: "English", hi: false, forced: false }],
      last_polled: "2024-01-02T00:00:00Z",
      active_job_id: null,
      active_job_status: null,
      active_job_progress: null,
    },
    {
      id: "movie:2",
      kind: "movie",
      ext_id: 2,
      title: "mango Movie",
      media_path: "/movies/mango.mkv",
      has_any_subs: false,
      missing_subtitles: [{ code2: "en", name: "English", hi: false, forced: false }],
      audio_language: [{ code2: "en", code3: "eng", name: "English", hi: false, forced: false }],
      last_polled: "2024-01-03T00:00:00Z",
      active_job_id: null,
      active_job_status: null,
      active_job_progress: null,
    },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue({
      items: MOCK_TITLE_ITEMS,
      total: MOCK_TITLE_ITEMS.length,
      last_refreshed_at: null,
    })
    vi.mocked(api.post).mockResolvedValue(MOCK_REFRESH_STARTED)
  })

  it("sorts items alphabetically by title by default, ignoring case", async () => {
    render(<WantedPage />, { wrapper })

    const rows = await waitFor(() => {
      const all = within(screen.getByRole("table")).getAllByRole("row")
      // First row is the header; the rest are item rows.
      const dataRows = all.slice(1)
      expect(dataRows.length).toBe(MOCK_TITLE_ITEMS.length)
      return dataRows
    })

    const renderedTitles = rows.map((row) =>
      within(row).getAllByRole("cell")[0].textContent,
    )
    expect(renderedTitles).toEqual(["Alpha Movie", "mango Movie", "zebra Movie"])
  })

  it("sorts titles with embedded numbers by magnitude (natural sort), not lexicographically", async () => {
    vi.mocked(api.get).mockResolvedValue({
      items: [
        {
          id: "ep:100",
          kind: "episode",
          ext_id: 100,
          title: "Show — Episode 100",
          media_path: "/series/s100.mkv",
          has_any_subs: false,
          missing_subtitles: [{ code2: "en", name: "English", hi: false, forced: false }],
          audio_language: [{ code2: "en", code3: "eng", name: "English", hi: false, forced: false }],
          last_polled: "2024-01-01T00:00:00Z",
          active_job_id: null,
          active_job_status: null,
          active_job_progress: null,
        },
        {
          id: "ep:10",
          kind: "episode",
          ext_id: 10,
          title: "Show — Episode 10",
          media_path: "/series/s10.mkv",
          has_any_subs: false,
          missing_subtitles: [{ code2: "en", name: "English", hi: false, forced: false }],
          audio_language: [{ code2: "en", code3: "eng", name: "English", hi: false, forced: false }],
          last_polled: "2024-01-02T00:00:00Z",
          active_job_id: null,
          active_job_status: null,
          active_job_progress: null,
        },
        {
          id: "ep:1",
          kind: "episode",
          ext_id: 1,
          title: "Show — Episode 1",
          media_path: "/series/s1.mkv",
          has_any_subs: false,
          missing_subtitles: [{ code2: "en", name: "English", hi: false, forced: false }],
          audio_language: [{ code2: "en", code3: "eng", name: "English", hi: false, forced: false }],
          last_polled: "2024-01-03T00:00:00Z",
          active_job_id: null,
          active_job_status: null,
          active_job_progress: null,
        },
        {
          id: "ep:2",
          kind: "episode",
          ext_id: 2,
          title: "Show — Episode 2",
          media_path: "/series/s2.mkv",
          has_any_subs: false,
          missing_subtitles: [{ code2: "en", name: "English", hi: false, forced: false }],
          audio_language: [{ code2: "en", code3: "eng", name: "English", hi: false, forced: false }],
          last_polled: "2024-01-04T00:00:00Z",
          active_job_id: null,
          active_job_status: null,
          active_job_progress: null,
        },
      ],
      total: 4,
      last_refreshed_at: null,
    })

    render(<WantedPage />, { wrapper })

    const rows = await waitFor(() => {
      const dataRows = within(screen.getByRole("table")).getAllByRole("row").slice(1)
      expect(dataRows.length).toBe(4)
      return dataRows
    })

    const renderedTitles = rows.map((row) =>
      within(row).getAllByRole("cell")[0].textContent,
    )
    expect(renderedTitles).toEqual([
      "Show — Episode 1",
      "Show — Episode 2",
      "Show — Episode 10",
      "Show — Episode 100",
    ])
  })

  it("sends the typed search term to the server instead of filtering client-side", async () => {
    // Search is applied server-side (see audio_to_subs/api/routes/wanted.py),
    // so the client's only job is to forward the term as a query param - it
    // must not re-filter the page it already received.
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Alpha Movie")).toBeInTheDocument()
    })

    await user.type(screen.getByPlaceholderText("Search…"), "MAN")

    await waitFor(() => {
      expect(api.get).toHaveBeenLastCalledWith(
        expect.stringContaining("search=MAN"),
      )
    })
  })
})
