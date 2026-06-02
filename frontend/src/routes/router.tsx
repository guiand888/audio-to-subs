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
import { ComingSoonPage } from "@/pages/ComingSoonPage"

// ── Root ─────────────────────────────────────────────────────────────────────

const rootRoute = createRootRoute({
  component: Outlet,
})

// ── Public ───────────────────────────────────────────────────────────────────

export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (search: Record<string, unknown>): { next: string } => ({
    next: typeof search.next === "string" ? search.next : "/wanted",
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
  component: () => <ComingSoonPage page="History" />,
})

const logsRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/logs",
  component: () => <ComingSoonPage page="Logs" />,
})

const settingsRoute = createRoute({
  getParentRoute: () => layoutRoute,
  path: "/settings",
  component: () => <ComingSoonPage page="Settings" />,
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
  ]),
])

export const router = createRouter({ routeTree })

// Ambient type registration for TanStack Router
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}
