import {
  createRouter,
  createRootRoute,
  createRoute,
  Outlet,
  useNavigate,
} from "@tanstack/react-router"
import { useEffect } from "react"
import { AppLayout } from "@/components/AppLayout"
import { LoginPage } from "@/pages/LoginPage"
import { WantedPage } from "@/pages/WantedPage"
import { QueuePage } from "@/pages/QueuePage"
import { HistoryPage } from "@/pages/HistoryPage"
import { LogsPage } from "@/pages/LogsPage"
import { SettingsPage } from "@/pages/SettingsPage"
import { JobDetailPage } from "@/pages/JobDetailPage"

// ── Root ─────────────────────────────────────────────────────────────────────

const rootRoute = createRootRoute({
  component: Outlet,
})

// ── Public ───────────────────────────────────────────────────────────────────

// Only same-origin relative paths are safe redirect targets; anything else
// (missing, "/login" itself, or a "//host" style protocol-relative URL) falls
// back to "/wanted". This is the single choke point for `next`, so LoginPage
// and AppLayout never have to re-validate it themselves.
function safeNext(value: unknown): string {
  if (
    typeof value === "string" &&
    value.startsWith("/") &&
    !value.startsWith("//") &&
    value !== "/login"
  ) {
    return value
  }
  return "/wanted"
}

export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (search: Record<string, unknown>): { next: string } => ({
    next: safeNext(search.next),
  }),
  component: LoginPage,
})

// ── Protected layout (auth guard lives in AppLayout) ─────────────────────────

const layoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "layout",
  component: AppLayout,
})

function IndexRedirect() {
  const navigate = useNavigate()
  useEffect(() => {
    void navigate({ to: "/wanted" })
  }, [navigate])
  return null
}

const indexRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/",
  component: IndexRedirect,
})

const wantedRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/wanted",
  component: WantedPage,
})

const queueRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/queue",
  component: QueuePage,
})

const historyRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/history",
  component: HistoryPage,
})

const logsRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/logs",
  component: LogsPage,
})

const settingsRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/settings",
  component: SettingsPage,
})

const jobDetailRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/jobs/$jobId",
  component: JobDetailPage,
})

// ── Tree ─────────────────────────────────────────────────────────────────────

const routeTree = rootRoute.addChildren([
  loginRoute,
  layoutRoute.addChildren([
    indexRoute,
    wantedRoute,
    queueRoute,
    historyRoute,
    logsRoute,
    settingsRoute,
    jobDetailRoute,
  ]),
])

export const router = createRouter({ routeTree })

// Ambient type registration for TanStack Router
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}
