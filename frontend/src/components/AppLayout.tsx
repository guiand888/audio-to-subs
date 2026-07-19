// Persistent layout: 200px fixed sidebar + 64px topbar.
// Mounts the global SSE stream (useJobsStream) once here.
// Auth guard: checks /api/auth/me on boot; redirects to /login only on a
// confirmed 401. Transient errors (502, 503, network) are treated as
// "backend not ready" and show a retry screen instead of bouncing to /login.

import { useEffect } from "react"
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router"
import {
  Clock,
  History,
  List,
  LogOut,
  PanelLeft,
  PanelLeftClose,
  Settings,
  Tv,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "./ui/button"
import { Separator } from "./ui/separator"
import { ThemeToggle } from "./ThemeToggle"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./ui/tooltip"
import { useJobsStream } from "@/hooks/useJobsStream"
import { useMe, useLogout } from "@/hooks/useAuth"
import { useSidebarCollapse } from "@/hooks/useSidebarCollapse"
import { useVersion } from "@/hooks/useVersion"
import { cn } from "@/lib/utils"

const navLinks = [
  { to: "/wanted", label: "Wanted", icon: Tv },
  { to: "/queue", label: "Queue", icon: Clock },
  { to: "/history", label: "History", icon: History },
  { to: "/logs", label: "Logs", icon: List },
  { to: "/settings", label: "Settings", icon: Settings },
] as const

export function AppLayout() {
  const navigate = useNavigate()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const { data: user, isLoading, error, isFetching, refetch } = useMe()
  const logout = useLogout()
  const { collapsed, toggle } = useSidebarCollapse()
  const version = useVersion()

  // True when useMe failed with a non-401 error (backend unreachable,
  // 502/503, network failure). A 401 is swallowed inside useMe's queryFn
  // (returns null), so any error that surfaces here is transient.
  const isBackendUnreachable = !!error

  // Mount the global SSE stream exactly once
  useJobsStream()

  // Redirect to /login only on confirmed unauthenticated (null user with no
  // error). When the backend is unreachable we keep the user on the current
  // page so they see the retry screen, not the login page.
  // The pathname !== "/login" guard prevents a self-referential redirect:
  // navigate() updates the router's reactive location before this route's
  // component tree fully unmounts, so without the guard this effect can
  // re-fire mid-transition with pathname already "/login" and produce
  // /login?next=%2Flogin.
  useEffect(() => {
    if (!isLoading && !user && !isBackendUnreachable && pathname !== "/login") {
      void navigate({
        to: "/login",
        search: { next: pathname },
      })
    }
  }, [user, isLoading, isBackendUnreachable, navigate, pathname])

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <span className="text-muted-foreground text-sm">Loading…</span>
      </div>
    )
  }

  if (isBackendUnreachable) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4">
        <span className="text-muted-foreground text-sm">
          {isFetching
            ? "Connecting to server…"
            : "Unable to reach the server."}
        </span>
        {!isFetching && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refetch()}
          >
            Retry
          </Button>
        )}
      </div>
    )
  }

  if (!user) return null

  const handleLogout = () => {
    logout.mutate(undefined, {
      onSuccess: () => {
        void navigate({ to: "/login", search: { next: "/wanted" } })
      },
      onError: () => {
        toast.error("Logout failed")
      },
    })
  }

  return (
    <TooltipProvider delayDuration={0}>
      <div className="flex h-screen overflow-hidden bg-background">
        {/* Sidebar — 200px expanded, 56px icon rail when collapsed */}
        <aside
          className={cn(
            "flex-none flex flex-col border-r bg-background transition-[width] duration-200 ease-in-out",
            collapsed ? "w-[56px]" : "w-[200px]",
          )}
        >
          {/* Brand */}
          <div className="flex h-16 items-center px-4 font-semibold text-sm tracking-tight">
            {collapsed ? "P" : "Parolesub"}
          </div>
          <Separator />

          {/* Nav links */}
          <nav className="flex-1 overflow-y-auto py-2">
            {navLinks.map(({ to, label, icon: Icon }) => {
              const active = pathname.startsWith(to)
              const link = (
                <Link
                  to={to}
                  className={cn(
                    "flex items-center gap-3 py-2 text-sm transition-colors hover:bg-accent hover:text-accent-foreground",
                    collapsed ? "justify-center px-0" : "px-4",
                    active
                      ? "border-l-2 border-primary bg-accent/50 font-medium"
                      : "border-l-2 border-transparent",
                  )}
                >
                  <Icon className="h-4 w-4 flex-none" />
                  {!collapsed && label}
                </Link>
              )

              return collapsed ? (
                <Tooltip key={to}>
                  <TooltipTrigger asChild>{link}</TooltipTrigger>
                  <TooltipContent side="right">{label}</TooltipContent>
                </Tooltip>
              ) : (
                <div key={to}>{link}</div>
              )
            })}
          </nav>

          {/* Version — ambient, tertiary metadata pinned to the sidebar
              bottom. Aligns with the brand/nav gutter (px-4). Hidden entirely
              in the collapsed icon rail: a version string can't render
              meaningfully in 56px, so we drop it like the brand drops to "P". */}
          {!collapsed && (
            <div className="mt-auto">
              <Separator />
              <div className="px-4 py-2">
                <span className="font-mono text-[11px] tabular-nums text-muted-foreground/70">
                  {version}
                </span>
              </div>
            </div>
          )}
        </aside>

        {/* Main area */}
        <div className="flex flex-1 flex-col min-w-0">
          {/* Topbar — 64px */}
          <header className="flex h-16 flex-none items-center justify-between border-b px-4">
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon"
                onClick={toggle}
                title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              >
                {collapsed ? (
                  <PanelLeft className="h-4 w-4" />
                ) : (
                  <PanelLeftClose className="h-4 w-4" />
                )}
              </Button>
            </div>
            <div className="flex items-center gap-2">
              <ThemeToggle />
              <div className="flex items-center gap-2">
                <span
                  className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground"
                  title={user.username}
                  aria-label={user.username}
                >
                  {user.username.charAt(0).toUpperCase()}
                </span>
                <span className="text-sm">{user.username}</span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleLogout}
                disabled={logout.isPending}
                className="gap-2"
              >
                <LogOut className="h-4 w-4" />
                Logout
              </Button>
            </div>
          </header>

          {/* Page content */}
          <main className="flex-1 overflow-auto">
            <Outlet />
          </main>
        </div>
      </div>
    </TooltipProvider>
  )
}
