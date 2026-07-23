import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
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
// back over SSE (see MockEventSource below). The refresh_id in this mock is
// ignored by the new useWantedRefresh hook: the client generates the id
// itself, sends it in the POST body, and uses it to filter SSE events.
// Tests that need to emit refresh_done read the actual id back via
// lastRefreshIdFromPost() below.
const MOCK_REFRESH_STARTED = {
  status: "started",
  refresh_id: "server-echoed-id",
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
// useWantedRefresh opens one against /api/jobs/stream as soon as a refresh
// starts. Tests grab the latest instance and call `.emit(...)` to simulate
// server-sent frames (including the stream_ready handshake that triggers
// the POST).
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
    // The onmessage handler triggers React state updates (setProgress in
    // useWantedRefresh); wrap it so React batches/flushes it the same way
    // it would a real browser event, avoiding "update not wrapped in
    // act(...)" warnings from these synthetic SSE frames.
    act(() => {
      this.onmessage?.({ data: JSON.stringify(data) })
    })
  }
}

// @ts-expect-error test-only polyfill for an API jsdom doesn't implement
global.EventSource = MockEventSource

// Extract the client-generated refresh_id from the most recent
// POST /api/wanted/refresh call. The hook generates a UUID client-side and
// sends it in the body; tests need it to address SSE frames to the right
// subscription filter inside useWantedRefresh.
function lastRefreshIdFromPost(): string {
  const calls = vi.mocked(api.post).mock.calls
  for (let i = calls.length - 1; i >= 0; i--) {
    const [path, body] = calls[i]
    if (path === "/api/wanted/refresh") {
      return (body as { refresh_id?: string }).refresh_id!
    }
  }
  throw new Error("No /api/wanted/refresh POST found")
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
    const refreshPromise = new Promise<typeof MOCK_REFRESH_STARTED>(() => {})
    vi.mocked(api.post).mockReturnValue(refreshPromise)

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      const button = screen.getByText("Refresh")
      expect(button).toBeInTheDocument()
      expect(button).not.toBeDisabled()
    })

    // Click the button
    await user.click(screen.getByText("Refresh"))

    // Should show loading state and disable button once the user clicks -
    // the hook sets progress.active=true synchronously in start(), before
    // the POST is even issued.
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

    // Should show loading state as soon as the user clicks.
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

    // The hook waits for stream_ready before POSTing so it can't miss
    // refresh_done on a fast refresh (race fix). Emit the handshake, then
    // the terminal frame addressed to whatever id the client generated.
    MockEventSource.latest()!.emit({ event: "stream_ready" })

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/wanted/refresh",
        expect.objectContaining({ item_type: "all" }),
      )
    })

    MockEventSource.latest()!.emit({
      event: "refresh_done",
      refresh_id: lastRefreshIdFromPost(),
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

    // The POST only fires after stream_ready arrives - emit it so the
    // mocked failure response is processed without waiting for the
    // 5s ready-timeout fallback.
    await waitFor(() => {
      expect(MockEventSource.latest()).toBeDefined()
    })
    MockEventSource.latest()!.emit({ event: "stream_ready" })

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

describe("WantedPage - Refresh race & watchdog regressions", () => {
  // These tests cover the failure mode that motivated the rewrite:
  // the old useRefreshProgress hook opened its EventSource AFTER POSTing,
  // so a fast refresh could publish refresh_done before pubsub.subscribe
  // completed and the UI would hang on "Refreshing..." forever. The new
  // useWantedRefresh hook waits for stream_ready before POSTing and falls
  // back to GET /api/wanted/refresh/{id} if SSE goes silent for 30s.

  beforeEach(() => {
    vi.clearAllMocks()
    MockEventSource.reset()
    vi.mocked(api.get).mockResolvedValue(MOCK_WANTED_EMPTY)
    vi.mocked(api.post).mockResolvedValue(MOCK_REFRESH_STARTED)
  })

  afterEach(() => {
    // Defensive: ensure fake timers never leak into the next test even if
    // an assertion throws before the cleanup runs.
    vi.useRealTimers()
  })

  it("stream_ready is emitted before POST /api/wanted/refresh (subscribe-first)", async () => {
    // Regression: the POST must not fire until stream_ready arrives. If it
    // fires earlier, the original race (events published before subscribe)
    // is reintroduced.
    const user = userEvent.setup()
    let resolvePost: (v: typeof MOCK_REFRESH_STARTED) => void
    const pending = new Promise<typeof MOCK_REFRESH_STARTED>((r) => {
      resolvePost = r
    })
    vi.mocked(api.post).mockReturnValue(pending)

    render(<WantedPage />, { wrapper })
    await waitFor(() => screen.getByText("Refresh"))
    await user.click(screen.getByText("Refresh"))

    // No POST before stream_ready.
    expect(vi.mocked(api.post)).not.toHaveBeenCalled()

    await waitFor(() => MockEventSource.latest() !== undefined)

    // stream_ready arrives -> POST fires immediately.
    MockEventSource.latest()!.emit({ event: "stream_ready" })
    await waitFor(() => {
      expect(vi.mocked(api.post)).toHaveBeenCalledWith(
        "/api/wanted/refresh",
        expect.objectContaining({ item_type: "all" }),
      )
    })

    // Finalize so the test ends cleanly.
    resolvePost!(MOCK_REFRESH_STARTED)
    MockEventSource.latest()!.emit({
      event: "refresh_done",
      refresh_id: lastRefreshIdFromPost(),
      status: "completed",
      movies_processed: 1,
      episodes_processed: 0,
    })
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalled()
    })
  })

  it("happy path: refresh_progress frames advance the bar before refresh_done", async () => {
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })
    await waitFor(() => screen.getByText("Refresh"))
    await user.click(screen.getByText("Refresh"))

    await waitFor(() => MockEventSource.latest() !== undefined)
    MockEventSource.latest()!.emit({ event: "stream_ready" })

    const id = await waitFor(() => lastRefreshIdFromPost())

    // Two intermediate progress frames should each advance processed/total.
    MockEventSource.latest()!.emit({
      event: "refresh_progress",
      refresh_id: id,
      processed: 1,
      total: 3,
      percent: 33,
      stage: "refreshing wanted",
    })
    await waitFor(() => {
      expect(screen.getByText("1 / 3")).toBeInTheDocument()
    })

    MockEventSource.latest()!.emit({
      event: "refresh_progress",
      refresh_id: id,
      processed: 2,
      total: 3,
      percent: 67,
      stage: "refreshing wanted",
    })
    await waitFor(() => {
      expect(screen.getByText("2 / 3")).toBeInTheDocument()
    })

    MockEventSource.latest()!.emit({
      event: "refresh_done",
      refresh_id: id,
      status: "completed",
      movies_processed: 2,
      episodes_processed: 1,
    })
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Refreshed 3 items")
    })
  })

  it("watchdog recovers from a missed refresh_done via GET status endpoint", async () => {
    // Simulates the original race: stream_ready is emitted, the POST
    // succeeds, but no refresh_done ever arrives (e.g. EventSource dropped
    // mid-stream). After 30s the watchdog must GET the persisted-state
    // endpoint and finalize from the snapshot.
    //
    // Uses fireEvent (not userEvent) because userEvent's internal delays
    // don't play well with fake timers; fireEvent.click is synchronous.
    vi.useFakeTimers()

    // GET /api/wanted/refresh/{id} - mock returns the terminal snapshot.
    // The request URL contains the client's refresh_id; echo it back so
    // the hook's filter logic is happy.
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path.startsWith("/api/wanted/refresh/")) {
        return {
          refresh_id: path.split("/").pop()!,
          status: "completed" as const,
          processed: 7,
          total: null,
          percent: 100,
          stage: "done",
          movies_processed: 4,
          episodes_processed: 3,
          error: null,
          updated_at: "2026-01-01T00:00:00Z",
        }
      }
      return MOCK_WANTED_EMPTY
    })

    render(<WantedPage />, { wrapper })
    await act(async () => {
      fireEvent.click(screen.getByText("Refresh"))
    })

    // Drain initial render + EventSource construction.
    await vi.advanceTimersByTimeAsync(0)
    expect(MockEventSource.latest()).toBeDefined()

    // stream_ready triggers doPost() synchronously inside emit's act().
    MockEventSource.latest()!.emit({ event: "stream_ready" })
    // Flush the POST resolution + watchdog arming.
    await vi.advanceTimersByTimeAsync(0)
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/api/wanted/refresh",
      expect.objectContaining({ item_type: "all" }),
    )

    // Advance past the watchdog threshold without delivering any SSE events.
    // advanceTimersByTimeAsync also flushes the microtask chain that the
    // watchdog's `await api.get(...)` runs on.
    await vi.advanceTimersByTimeAsync(31_000)

    expect(vi.mocked(api.get)).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/wanted\/refresh\/[0-9a-f-]+/),
    )
    expect(toast.success).toHaveBeenCalledWith("Refreshed 7 items")

    vi.useRealTimers()
  })

  it("watchdog surfaces an error when status endpoint returns 404", async () => {
    // Same race scenario but the persisted state has expired (TTL elapsed)
    // or never existed. The hook must surface a clear error and reset so
    // the user can retry, rather than hang.
    vi.useFakeTimers()

    vi.mocked(api.get).mockRejectedValue(new ApiError(404, "expired"))

    render(<WantedPage />, { wrapper })
    await act(async () => {
      fireEvent.click(screen.getByText("Refresh"))
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(MockEventSource.latest()).toBeDefined()

    MockEventSource.latest()!.emit({ event: "stream_ready" })
    await vi.advanceTimersByTimeAsync(0)
    expect(vi.mocked(api.post)).toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(31_000)

    expect(toast.error).toHaveBeenCalledWith("Refresh status unknown, please retry")

    // Flush the resetToIdle() state update that runs after the toast.
    await vi.advanceTimersByTimeAsync(0)

    // UI must reset to idle so the user can retry.
    expect(screen.getByText("Refresh")).toBeInTheDocument()

    vi.useRealTimers()
  })

  it("watchdog keeps waiting (no error) when the persisted snapshot shows advancing progress", async () => {
    // A large-library refresh (e.g. many episodes) can legitimately go a
    // full watchdog cycle without a live refresh_progress SSE frame. As long
    // as the persisted snapshot's `processed` count keeps advancing between
    // checks, the hook must NOT toast an error or reset - it should adopt
    // the snapshot into the visible progress and keep waiting.
    vi.useFakeTimers()

    let getCalls = 0
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path.startsWith("/api/wanted/refresh/")) {
        getCalls += 1
        if (getCalls === 1) {
          return {
            refresh_id: path.split("/").pop()!,
            status: "started" as const,
            processed: 50,
            total: null,
            percent: 0,
            stage: "syncing episodes",
            movies_processed: 0,
            episodes_processed: 0,
            error: null,
            updated_at: "2026-01-01T00:00:00Z",
          }
        }
        return {
          refresh_id: path.split("/").pop()!,
          status: "completed" as const,
          processed: 130,
          total: null,
          percent: 100,
          stage: "done",
          movies_processed: 30,
          episodes_processed: 100,
          error: null,
          updated_at: "2026-01-01T00:00:01Z",
        }
      }
      return MOCK_WANTED_EMPTY
    })

    render(<WantedPage />, { wrapper })
    await act(async () => {
      fireEvent.click(screen.getByText("Refresh"))
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(MockEventSource.latest()).toBeDefined()

    MockEventSource.latest()!.emit({ event: "stream_ready" })
    await vi.advanceTimersByTimeAsync(0)
    expect(vi.mocked(api.post)).toHaveBeenCalled()

    // First watchdog fire: snapshot shows processed=50 (up from unset) ->
    // adopt it, no error, no reset. (Plain assertions, not waitFor - waitFor
    // polls via real timers, which never fire while fake timers are active.)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000)
    })
    expect(toast.error).not.toHaveBeenCalled()
    expect(screen.getByText("50 items")).toBeInTheDocument()

    // Second watchdog fire: snapshot is now terminal -> finalize normally.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000)
    })
    expect(toast.error).not.toHaveBeenCalled()
    expect(toast.success).toHaveBeenCalledWith("Refreshed 130 items")

    vi.useRealTimers()
  })

  it("watchdog gives up only after repeated checks show zero progress", async () => {
    // The flip side: if the persisted snapshot's `processed` count never
    // moves across several consecutive watchdog checks, the refresh really
    // is stuck (or the connection is dead) and the hook must eventually
    // surface the error - just not on the very first miss.
    vi.useFakeTimers()

    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path.startsWith("/api/wanted/refresh/")) {
        return {
          refresh_id: path.split("/").pop()!,
          status: "started" as const,
          processed: 10,
          total: null,
          percent: 0,
          stage: "syncing episodes",
          movies_processed: 0,
          episodes_processed: 0,
          error: null,
          updated_at: "2026-01-01T00:00:00Z",
        }
      }
      return MOCK_WANTED_EMPTY
    })

    render(<WantedPage />, { wrapper })
    await act(async () => {
      fireEvent.click(screen.getByText("Refresh"))
    })
    await vi.advanceTimersByTimeAsync(0)
    expect(MockEventSource.latest()).toBeDefined()

    MockEventSource.latest()!.emit({ event: "stream_ready" })
    await vi.advanceTimersByTimeAsync(0)
    expect(vi.mocked(api.post)).toHaveBeenCalled()

    // First check only establishes the processed=10 baseline (nothing to
    // compare against yet) - no error. Second check: still 10, one stalled
    // check - still no error.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000)
    })
    expect(toast.error).not.toHaveBeenCalled()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000)
    })
    expect(toast.error).not.toHaveBeenCalled()

    // Third check: still 10, second consecutive stall -> genuinely give up.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000)
    })
    expect(toast.error).toHaveBeenCalledWith("Refresh status unknown, please retry")

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByText("Refresh")).toBeInTheDocument()

    vi.useRealTimers()
  })
})


describe("WantedPage - Scope selector (All/Missing/No subs)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    MockEventSource.reset()
    vi.mocked(api.get).mockResolvedValue(MOCK_WANTED_EMPTY)
    vi.mocked(api.post).mockResolvedValue(MOCK_REFRESH_STARTED)
  })

  function scopeTablist() {
    return screen.getByRole("tablist", { name: "Scope" })
  }

  it("renders all three scope states, replacing the old no-subs toggle", async () => {
    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(scopeTablist()).toBeInTheDocument()
    })
    expect(within(scopeTablist()).getByRole("tab", { name: "All" })).toBeInTheDocument()
    expect(
      within(scopeTablist()).getByRole("tab", { name: "Missing" }),
    ).toBeInTheDocument()
    expect(
      within(scopeTablist()).getByRole("tab", { name: "No subs" }),
    ).toBeInTheDocument()
    // The old binary toggle must be gone.
    expect(screen.queryByText("No subtitles only")).not.toBeInTheDocument()
  })

  it("selecting a scope sends it to the server as a display filter", async () => {
    const user = userEvent.setup()
    render(<WantedPage />, { wrapper })

    await waitFor(() => scopeTablist())
    await user.click(within(scopeTablist()).getByRole("tab", { name: "Missing" }))

    await waitFor(() => {
      expect(api.get).toHaveBeenLastCalledWith(
        expect.stringContaining("scope=missing"),
      )
    })

    await user.click(within(scopeTablist()).getByRole("tab", { name: "No subs" }))
    await waitFor(() => {
      expect(api.get).toHaveBeenLastCalledWith(
        expect.stringContaining("scope=no_subs"),
      )
    })
  })

  it("selecting a scope does NOT trigger a refresh (sync stays decoupled from display)", async () => {
    const user = userEvent.setup()
    render(<WantedPage />, { wrapper })

    await waitFor(() => scopeTablist())
    await user.click(within(scopeTablist()).getByRole("tab", { name: "Missing" }))
    await user.click(within(scopeTablist()).getByRole("tab", { name: "No subs" }))

    // Only GETs for the list (and no /api/wanted/refresh POST) should have
    // happened - selecting a scope must never narrow or trigger a re-sync.
    expect(api.post).not.toHaveBeenCalledWith(
      "/api/wanted/refresh",
      expect.anything(),
    )
  })

  it("Refresh still syncs the full library regardless of the active scope", async () => {
    const user = userEvent.setup()
    render(<WantedPage />, { wrapper })

    await waitFor(() => scopeTablist())
    await user.click(within(scopeTablist()).getByRole("tab", { name: "No subs" }))
    await user.click(screen.getByText("Refresh"))

    await waitFor(() => {
      expect(MockEventSource.latest()).toBeDefined()
    })
    MockEventSource.latest()!.emit({ event: "stream_ready" })

    await waitFor(() => {
      // The refresh request carries item_type only - no scope field at all.
      const call = vi
        .mocked(api.post)
        .mock.calls.find(([path]) => path === "/api/wanted/refresh")
      expect(call).toBeDefined()
      const body = call![1] as Record<string, unknown>
      expect(body.item_type).toBe("all")
      expect(body).not.toHaveProperty("scope")
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
      expect(MockEventSource.latest()).toBeDefined()
    })
    // stream_ready triggers the POST (subscribe-first protocol).
    MockEventSource.latest()!.emit({ event: "stream_ready" })

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/wanted/refresh",
        expect.objectContaining({ item_type: "movie" }),
      )
    })

    MockEventSource.latest()!.emit({
      event: "refresh_done",
      refresh_id: lastRefreshIdFromPost(),
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
      expect(MockEventSource.latest()).toBeDefined()
    })
    MockEventSource.latest()!.emit({ event: "stream_ready" })

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/wanted/refresh",
        expect.objectContaining({ item_type: "episode" }),
      )
    })

    MockEventSource.latest()!.emit({
      event: "refresh_done",
      refresh_id: lastRefreshIdFromPost(),
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
      expect(MockEventSource.latest()).toBeDefined()
    })
    MockEventSource.latest()!.emit({ event: "stream_ready" })

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/wanted/refresh",
        expect.objectContaining({ item_type: "all" }),
      )
    })

    MockEventSource.latest()!.emit({
      event: "refresh_done",
      refresh_id: lastRefreshIdFromPost(),
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
