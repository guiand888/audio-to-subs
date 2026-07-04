import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { toast } from "sonner"
import { api } from "@/lib/api"
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
      public readonly detail: string,
    ) {
      super(detail)
      this.name = "ApiError"
    }
  },
}))

const MOCK_WANTED_EMPTY = {
  items: [],
  total: 0,
  last_refreshed_at: null,
}

const MOCK_REFRESH_SUCCESS = {
  status: "completed",
  movies_processed: 5,
  episodes_processed: 3,
  error: null,
}

const MOCK_REFRESH_FAILURE = {
  status: "failed",
  movies_processed: 0,
  episodes_processed: 0,
  error: "Connection failed",
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
    vi.mocked(api.get).mockResolvedValue(MOCK_WANTED_EMPTY)
    vi.mocked(api.post).mockResolvedValue(MOCK_REFRESH_SUCCESS)
  })

  it("renders Refresh button with dropdown", async () => {
    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Refresh")).toBeInTheDocument()
    })
  })

  it("dropdown has All Items option", async () => {
    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      const dropdown = screen.getByRole("combobox")
      expect(dropdown).toBeInTheDocument()
    })

    // "All Items" is already the default selection (shown in the trigger);
    // opening the dropdown adds a second match in the option list.
    const user = userEvent.setup()
    await user.click(screen.getByRole("combobox"))
    await waitFor(() => {
      expect(screen.getAllByText("All Items").length).toBeGreaterThan(0)
    })
  })

  it("dropdown has Movies Only option", async () => {
    render(<WantedPage />, { wrapper })

    const user = userEvent.setup()
    await user.click(screen.getByRole("combobox"))
    await waitFor(() => {
      expect(screen.getByText("Movies Only")).toBeInTheDocument()
    })
  })

  it("dropdown has TV Series Only option", async () => {
    render(<WantedPage />, { wrapper })

    const user = userEvent.setup()
    await user.click(screen.getByRole("combobox"))
    await waitFor(() => {
      expect(screen.getByText("TV Series Only")).toBeInTheDocument()
    })
  })

  it("Refresh button is disabled during refresh", async () => {
    const user = userEvent.setup()
    let resolveRefresh: (value: typeof MOCK_REFRESH_SUCCESS) => void
    const refreshPromise = new Promise<typeof MOCK_REFRESH_SUCCESS>((resolve) => {
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

    // Should show loading state and disable button
    await waitFor(() => {
      const button = screen.getByText("Refreshing...")
      expect(button).toBeInTheDocument()
      expect(button.closest("button")).toBeDisabled()
    })

    // Resolve the promise so the test doesn't leave a dangling act() warning
    resolveRefresh!(MOCK_REFRESH_SUCCESS)
  })

  it("shows loading state during refresh", async () => {
    const user = userEvent.setup()
    let resolveRefresh: (value: typeof MOCK_REFRESH_SUCCESS) => void
    const refreshPromise = new Promise<typeof MOCK_REFRESH_SUCCESS>((resolve) => {
      resolveRefresh = resolve
    })
    vi.mocked(api.post).mockReturnValue(refreshPromise)

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Refresh")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Refresh"))

    // Should show loading state
    await waitFor(() => {
      expect(screen.getByText("Refreshing...")).toBeInTheDocument()
    })

    resolveRefresh!(MOCK_REFRESH_SUCCESS)
  })

  it("shows success notification on completion", async () => {
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText("Refresh")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Refresh"))

    // Wait for the refresh to complete and success to be processed
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalled()
    })
  })

  it("shows error notification on failure", async () => {
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

describe("WantedPage - Dropdown Selection", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue(MOCK_WANTED_EMPTY)
    vi.mocked(api.post).mockResolvedValue(MOCK_REFRESH_SUCCESS)
  })

  it("can select different refresh scopes from dropdown", async () => {
    const user = userEvent.setup()

    render(<WantedPage />, { wrapper })

    // Open dropdown
    await waitFor(() => {
      expect(screen.getByRole("combobox")).toBeInTheDocument()
    })
    await user.click(screen.getByRole("combobox"))

    // Select Movies Only
    await waitFor(() => {
      expect(screen.getByText("Movies Only")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Movies Only"))

    // Should now be able to click refresh with movies only scope
    await user.click(screen.getByText("Refresh"))

    // Verify the API was called with the correct scope
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/wanted/refresh", { item_type: "movie" })
    })
  })
})
