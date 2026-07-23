import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { LoginPage } from "./LoginPage"

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
}))

vi.mock("@/routes/router", () => ({
  loginRoute: {
    useSearch: () => ({ next: "/wanted" }),
  },
}))

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
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

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe("LoginPage - error messages", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("shows 'Invalid username or password' on 401", async () => {
    const user = userEvent.setup()
    vi.mocked(api.post).mockRejectedValue(
      new ApiError(401, "Invalid username or password"),
    )

    render(<LoginPage />, { wrapper })

    await user.type(screen.getByLabelText("Username"), "admin")
    await user.type(screen.getByLabelText("Password"), "wrongpass")
    await user.click(screen.getByText("Sign in"))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Invalid username or password")
    })
  })

  it("shows 'Server is starting up' on 502 (backend not ready)", async () => {
    const user = userEvent.setup()
    vi.mocked(api.post).mockRejectedValue(new ApiError(502, "Bad Gateway"))

    render(<LoginPage />, { wrapper })

    await user.type(screen.getByLabelText("Username"), "admin")
    await user.type(screen.getByLabelText("Password"), "admin")
    await user.click(screen.getByText("Sign in"))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Server is starting up. Please wait a moment, then try again.",
      )
    })
  })

  it("shows 'Server is starting up' on network error (connection refused)", async () => {
    const user = userEvent.setup()
    vi.mocked(api.post).mockRejectedValue(new TypeError("Failed to fetch"))

    render(<LoginPage />, { wrapper })

    await user.type(screen.getByLabelText("Username"), "admin")
    await user.type(screen.getByLabelText("Password"), "admin")
    await user.click(screen.getByText("Sign in"))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Server is starting up. Please wait a moment, then try again.",
      )
    })
  })
})

describe("LoginPage - branding (M13)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("renders the ParoleSub logo above the sign-in form with accessible alt text", () => {
    render(<LoginPage />, { wrapper })

    const logos = screen.getAllByAltText("ParoleSub")
    expect(logos.length).toBeGreaterThanOrEqual(1)
    logos.forEach((logo) => expect(logo.tagName).toBe("IMG"))

    // The logo lives above the username field in DOM order.
    const usernameField = screen.getByLabelText("Username")
    expect(
      logos[0].compareDocumentPosition(usernameField) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })
})
