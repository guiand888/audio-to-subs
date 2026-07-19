import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useMe } from "@/hooks/useAuth"
import { AppLayout } from "./AppLayout"

// Mock router hooks. useRouterState takes a selector and applies it to the
// router state; we return a fixed pathname.
const mockNavigate = vi.fn()
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => mockNavigate,
  useRouterState: ({ select }: { select: (s: unknown) => unknown }) =>
    select({ location: { pathname: "/wanted" } }),
  Link: ({ children, ...props }: { children: React.ReactNode } & Record<string, unknown>) => (
    <a {...(props as React.AnchorHTMLAttributes<HTMLAnchorElement>)}>{children}</a>
  ),
  Outlet: () => <div data-testid="outlet" />,
}))

vi.mock("@/hooks/useJobsStream", () => ({
  useJobsStream: () => {},
}))

// Shared mutable state so individual tests can drive collapsed/toggle.
const sidebarState = { collapsed: false, toggle: vi.fn() }
vi.mock("@/hooks/useSidebarCollapse", () => ({
  useSidebarCollapse: () => ({
    collapsed: sidebarState.collapsed,
    set: vi.fn(),
    toggle: sidebarState.toggle,
  }),
}))

vi.mock("@/hooks/useAuth", () => ({
  useMe: vi.fn(),
  useLogout: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock("./ThemeToggle", () => ({
  ThemeToggle: () => <div data-testid="theme-toggle" />,
}))

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

describe("AppLayout - backend unreachable", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("shows retry screen instead of redirecting to /login on transient error", () => {
    vi.mocked(useMe).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new TypeError("Failed to fetch"),
      isFetching: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useMe>)

    render(<AppLayout />)

    expect(screen.getByText("Unable to reach the server.")).toBeInTheDocument()
    expect(screen.getByText("Retry")).toBeInTheDocument()
    // Must NOT redirect to /login on a transient error
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it("shows 'Connecting to server…' while retrying", () => {
    vi.mocked(useMe).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new TypeError("Failed to fetch"),
      isFetching: true,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useMe>)

    render(<AppLayout />)

    expect(screen.getByText("Connecting to server…")).toBeInTheDocument()
    expect(screen.queryByText("Retry")).not.toBeInTheDocument()
  })

  it("calls refetch when Retry button is clicked", async () => {
    const user = userEvent.setup()
    const mockRefetch = vi.fn().mockResolvedValue({})

    vi.mocked(useMe).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new TypeError("Failed to fetch"),
      isFetching: false,
      refetch: mockRefetch,
    } as unknown as ReturnType<typeof useMe>)

    render(<AppLayout />)

    await user.click(screen.getByText("Retry"))
    expect(mockRefetch).toHaveBeenCalledTimes(1)
  })

  it("redirects to /login only on confirmed 401 (null user, no error)", () => {
    vi.mocked(useMe).mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
      isFetching: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useMe>)

    render(<AppLayout />)

    expect(mockNavigate).toHaveBeenCalledWith({
      to: "/login",
      search: { next: "/wanted" },
    })
  })
})

describe("AppLayout - collapsible sidebar", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sidebarState.collapsed = false
    sidebarState.toggle = vi.fn()
    vi.mocked(useMe).mockReturnValue({
      data: { username: "tester" },
      isLoading: false,
      error: null,
      isFetching: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useMe>)
  })

  it("renders the collapse toggle button", () => {
    render(<AppLayout />)
    expect(
      screen.getByRole("button", { name: "Collapse sidebar" }),
    ).toBeInTheDocument()
  })

  it("calls toggle when the collapse button is clicked", async () => {
    const user = userEvent.setup()
    render(<AppLayout />)
    await user.click(
      screen.getByRole("button", { name: "Collapse sidebar" }),
    )
    expect(sidebarState.toggle).toHaveBeenCalledTimes(1)
  })

  it("hides nav labels and shows a thin rail when collapsed", () => {
    sidebarState.collapsed = true
    render(<AppLayout />)
    // Brand collapses to a monogram
    expect(screen.queryByText("Parolesub")).not.toBeInTheDocument()
    expect(screen.getByText("P")).toBeInTheDocument()
    // Toggle now offers to expand
    expect(
      screen.getByRole("button", { name: "Expand sidebar" }),
    ).toBeInTheDocument()
  })
})
