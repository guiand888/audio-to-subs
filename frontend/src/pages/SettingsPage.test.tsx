import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { SettingsPage } from "./SettingsPage"
import {
  BAZARR_ERROR_CODES,
  BAZARR_ERROR_MESSAGES,
} from "@/components/settings/BazarrSettingsForm"

// vi.mock calls are hoisted to the top of the file by vitest, so they must be
// declared once at module scope (not inside individual `it` blocks) - the
// mocked module is shared across all tests in the file, configured per-test
// via vi.mocked(...).mockResolvedValue/mockReturnValue in beforeEach/tests.
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// SettingsPage's unsaved-changes guard uses useBlocker, which requires a
// RouterProvider context we don't set up here - stub it to a no-op since
// these tests exercise the Bazarr connection/config UI, not navigation.
vi.mock("@tanstack/react-router", () => ({
  useBlocker: () => ({ status: "idle" as const, proceed: undefined, reset: undefined }),
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
      public readonly detail: string,
    ) {
      super(detail)
      this.name = "ApiError"
    }
  },
}))

const MOCK_SETTINGS = {
  mistral_model: "voxtral-mini-latest",
  mistral_rate_usd_per_minute: 0.003,
  mistral_input_token_rate_usd: null,
  mistral_output_token_rate_usd: null,
  bazarr_poll_interval: 3600,
  bazarr_track_no_subs: false,
  bazarr_url: "http://localhost:6767",
  bazarr_api_key: "test-api-key",
  bazarr_timeout: 30.0,
  path_mappings: [],
  default_language: "en",
  default_output_format: "srt",
  movies_root_path: "/movies",
  tv_root_path: "/tv",
  subtitles_same_directory: true,
  max_audio_length: 900,
}

const MOCK_CONNECTION_SUCCESS = {
  success: true,
  message: "Connected to Bazarr successfully",
  error: null,
}

const MOCK_CONNECTION_FAILURE = {
  success: false,
  message: null,
  error: "connection_failed",
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

describe("SettingsPage - Bazarr Connection Test", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue(MOCK_SETTINGS)
    vi.mocked(api.patch).mockResolvedValue(MOCK_SETTINGS)
    vi.mocked(api.post).mockResolvedValue(MOCK_CONNECTION_SUCCESS)
  })

  it("renders Test Connection button when Bazarr URL is configured", async () => {
    render(<SettingsPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Test Connection")).toBeInTheDocument()
    })
  })

  it("Test Connection button is disabled when Bazarr URL is empty", async () => {
    vi.mocked(api.get).mockResolvedValue({ ...MOCK_SETTINGS, bazarr_url: null })

    render(<SettingsPage />, { wrapper })

    await waitFor(() => {
      const button = screen.getByText("Test Connection")
      expect(button).toBeInTheDocument()
      expect(button).toBeDisabled()
    })
  })

  it("shows loading state when connection test is in progress", async () => {
    const user = userEvent.setup()
    let resolveConnectionTest: (value: typeof MOCK_CONNECTION_SUCCESS) => void
    const connectionTestPromise = new Promise<typeof MOCK_CONNECTION_SUCCESS>((resolve) => {
      resolveConnectionTest = resolve
    })
    vi.mocked(api.post).mockReturnValue(connectionTestPromise)

    render(<SettingsPage />, { wrapper })

    await waitFor(() => {
      const button = screen.getByText("Test Connection")
      expect(button).toBeInTheDocument()
      expect(button).not.toBeDisabled()
    })

    // Click the button
    await user.click(screen.getByText("Test Connection"))

    // Should show loading state
    await waitFor(() => {
      expect(screen.getByText("Testing...")).toBeInTheDocument()
    })

    // Resolve the promise so the test doesn't leave a dangling act() warning
    resolveConnectionTest!(MOCK_CONNECTION_SUCCESS)
  })

  it("shows success indicator on successful connection test", async () => {
    const user = userEvent.setup()

    render(<SettingsPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Test Connection")).toBeInTheDocument()
    })

    await user.click(screen.getByText("Test Connection"))

    // Success is surfaced via a toast and the "Connection failed" text going
    // away (no dedicated test id exists on the success checkmark icon).
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Connected to Bazarr successfully")
    })
    expect(screen.queryByText("Connection failed")).not.toBeInTheDocument()
  })

  it("shows error message on failed connection test", async () => {
    vi.mocked(api.post).mockResolvedValue(MOCK_CONNECTION_FAILURE)
    const user = userEvent.setup()

    render(<SettingsPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Test Connection")).toBeInTheDocument()
    })

    await user.click(screen.getByText("Test Connection"))

    // Wait for error state
    await waitFor(() => {
      expect(screen.getByText("Connection failed")).toBeInTheDocument()
    })
  })
})

describe("SettingsPage - Bazarr Configuration Section", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue(MOCK_SETTINGS)
    vi.mocked(api.patch).mockResolvedValue(MOCK_SETTINGS)
    vi.mocked(api.post).mockResolvedValue(MOCK_CONNECTION_SUCCESS)
  })

  it("renders Bazarr configuration section", async () => {
    render(<SettingsPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText(/Bazarr Configuration/i)).toBeInTheDocument()
    })
  })

  it("renders Bazarr URL input field with configured value", async () => {
    render(<SettingsPage />, { wrapper })

    await waitFor(() => {
      const urlInput = screen.getByLabelText(/Bazarr API URL/i)
      expect(urlInput).toBeInTheDocument()
      expect(urlInput).toHaveValue("http://localhost:6767")
    })
  })
})

describe("SettingsPage - Save Settings change tracking", () => {
  it("clears the unsaved-changes indicator after a successful save", async () => {
    // Model a real backend: GET reflects whatever the last PATCH persisted,
    // instead of always returning the same static object. This is what
    // exposes the bug - a mock that always resolves the same MOCK_SETTINGS
    // would pass even with the indicator stuck, because it never simulates
    // the server actually remembering the save.
    let persisted = { ...MOCK_SETTINGS }
    vi.mocked(api.get).mockImplementation(() => Promise.resolve({ ...persisted }))
    vi.mocked(api.patch).mockImplementation((_url: unknown, body: unknown) => {
      persisted = { ...persisted, ...(body as object) }
      return Promise.resolve({ ...persisted })
    })

    const user = userEvent.setup()
    render(<SettingsPage />, { wrapper })

    const input = await screen.findByLabelText(/Movies Root Path/i)
    await user.clear(input)
    await user.type(input, "/media/movies")

    await waitFor(() => {
      expect(screen.getByText("1 change")).toBeInTheDocument()
    })

    await user.click(screen.getByText("Save Settings"))

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Settings saved")
    })

    await waitFor(() => {
      expect(screen.queryByText(/^\d+ changes?$/)).not.toBeInTheDocument()
    })
  })

  it("clears the indicator after saving a new Bazarr API key, even though the server always masks it back", async () => {
    // Mirrors the real backend: SettingsResponse.sanitized() replaces
    // bazarr_api_key with "***MASKED***" in every response once it's set
    // (audio_to_subs/api/routes/settings.py). A form that never re-syncs its
    // baseline from a fresh GET/PATCH response will keep comparing the raw
    // key the user typed against the masked placeholder forever.
    let persisted: Record<string, unknown> = { ...MOCK_SETTINGS, bazarr_api_key: null }
    const sanitize = (s: Record<string, unknown>) => ({
      ...s,
      bazarr_api_key: s.bazarr_api_key ? "***MASKED***" : null,
    })
    vi.mocked(api.get).mockImplementation(() => Promise.resolve(sanitize(persisted)))
    vi.mocked(api.patch).mockImplementation((_url: unknown, body: unknown) => {
      persisted = { ...persisted, ...(body as object) }
      return Promise.resolve(sanitize(persisted))
    })

    const user = userEvent.setup()
    render(<SettingsPage />, { wrapper })

    const apiKeyInput = await screen.findByLabelText(/^API Key$/i)
    await user.type(apiKeyInput, "sk-real-secret-key")

    await waitFor(() => {
      expect(screen.getByText("1 change")).toBeInTheDocument()
    })

    await user.click(screen.getByText("Save Settings"))

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Settings saved")
    })

    await waitFor(() => {
      expect(screen.queryByText(/^\d+ changes?$/)).not.toBeInTheDocument()
    })
  })

  it("clears the indicator when modifying an already-set API key (masked-to-masked refetch)", async () => {
    // The case the previous test doesn't cover: the key is ALREADY set
    // (masked) before this edit, so the post-save refetch payload is
    // masked -> masked - deeply equal to what's already cached. React
    // Query's structural sharing keeps the same object reference in that
    // case, so a form that resyncs its baseline only via a useEffect keyed
    // on the settings object (and never fires because the reference never
    // changes) leaves the counter stuck forever, even though the save
    // itself succeeded.
    let persisted: Record<string, unknown> = {
      ...MOCK_SETTINGS,
      bazarr_api_key: "old-secret-key",
    }
    const sanitize = (s: Record<string, unknown>) => ({
      ...s,
      bazarr_api_key: s.bazarr_api_key ? "***MASKED***" : null,
    })
    vi.mocked(api.get).mockImplementation(() => Promise.resolve(sanitize(persisted)))
    vi.mocked(api.patch).mockImplementation((_url: unknown, body: unknown) => {
      persisted = { ...persisted, ...(body as object) }
      return Promise.resolve(sanitize(persisted))
    })

    const user = userEvent.setup()
    render(<SettingsPage />, { wrapper })

    const apiKeyInput = await screen.findByLabelText(/^API Key$/i)
    await waitFor(() => {
      expect(apiKeyInput).toHaveValue("***MASKED***")
    })

    await user.clear(apiKeyInput)
    await user.type(apiKeyInput, "sk-new-secret-key")

    await waitFor(() => {
      expect(screen.getByText("1 change")).toBeInTheDocument()
    })

    await user.click(screen.getByText("Save Settings"))

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Settings saved")
    })

    await waitFor(() => {
      expect(screen.queryByText(/^\d+ changes?$/)).not.toBeInTheDocument()
    })
  })
})

describe("SettingsPage - Test Connection error UX", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue(MOCK_SETTINGS)
    vi.mocked(api.patch).mockResolvedValue(MOCK_SETTINGS)
  })

  // BAZARR_ERROR_CODES (not Object.keys(BAZARR_ERROR_MESSAGES)) is the
  // source of truth for which codes to exercise here, so a typo'd/renamed
  // key in the map can't silently satisfy this table - it fails to compile
  // against BAZARR_ERROR_MESSAGES's Record<BazarrErrorCode, string> type
  // instead.
  const errorScenarios = [
    ...BAZARR_ERROR_CODES.map((errorCode) => ({
      name: `maps error code '${errorCode}' to its friendly message`,
      error: errorCode as string,
      message: null as string | null,
      expectedToast: BAZARR_ERROR_MESSAGES[errorCode],
    })),
    {
      name: "falls back to response.message when the error code is unknown",
      error: "future_error_code_not_yet_in_map",
      message: "Something specific went wrong",
      expectedToast: "Something specific went wrong",
    },
    {
      name: "falls back to 'Unknown error' when error code is unknown and message is null",
      error: "future_error_code_not_yet_in_map",
      message: null,
      expectedToast: "Unknown error",
    },
  ]

  it.each(errorScenarios)("$name", async ({ error, message, expectedToast }) => {
    vi.mocked(api.post).mockResolvedValue({ success: false, message, error })

    const user = userEvent.setup()
    render(<SettingsPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Test Connection")).toBeInTheDocument()
    })

    await user.click(screen.getByText("Test Connection"))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(expectedToast)
    })
  })
})
