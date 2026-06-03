// Persistent layout: 200px fixed sidebar + 64px topbar.
// Mounts the global SSE stream (useJobsStream) once here.
// Auth guard: checks /api/auth/me on boot; redirects to /login if 401.

import { useEffect } from "react"
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router"
import {
  Clock,
  History,
  List,
  LogOut,
  Settings,
  Tv,
} from "lucide-react"
import { toast } from "sonner"
import { Button } from "./ui/button"
import { Separator } from "./ui/separator"
import { ThemeToggle } from "./ThemeToggle"
import { useJobsStream } from "@/hooks/useJobsStream"
import { useMe, useLogout } from "@/hooks/useAuth"
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
  const { data: user, isLoading } = useMe()
  const logout = useLogout()

  // Mount the global SSE stream exactly once
  useJobsStream()

  // Redirect to /login if not authenticated
  useEffect(() => {
    if (!isLoading && !user) {
      void navigate({
        to: "/login",
        search: { next: pathname },
      })
    }
  }, [user, isLoading, navigate, pathname])

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <span className="text-muted-foreground text-sm">Loading…</span>
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
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar — 200px fixed */}
      <aside className="w-[200px] flex-none flex flex-col border-r bg-background">
        {/* Brand */}
        <div className="flex h-16 items-center px-4 font-semibold text-sm tracking-tight">
          audio-to-subs
        </div>
        <Separator />

        {/* Nav links */}
        <nav className="flex-1 overflow-y-auto py-2">
          {navLinks.map(({ to, label, icon: Icon }) => {
            const active = pathname.startsWith(to)
            return (
              <Link
                key={to}
                to={to}
                className={cn(
                  "flex items-center gap-3 px-4 py-2 text-sm transition-colors hover:bg-accent hover:text-accent-foreground",
                  active
                    ? "border-l-2 border-primary bg-accent/50 font-medium"
                    : "border-l-2 border-transparent",
                )}
              >
                <Icon className="h-4 w-4 flex-none" />
                {label}
              </Link>
            )
          })}
        </nav>
      </aside>

      {/* Main area */}
      <div className="flex flex-1 flex-col min-w-0">
        {/* Topbar — 64px */}
        <header className="flex h-16 flex-none items-center justify-between border-b px-4">
          <span className="text-sm text-muted-foreground">
            {user.username}
          </span>
          <div className="flex items-center gap-1">
            <ThemeToggle />
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
  )
}
