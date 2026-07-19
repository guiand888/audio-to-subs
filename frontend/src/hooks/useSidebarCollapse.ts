// Sidebar collapse state, persisted in localStorage so the user's
// expanded/collapsed preference survives reloads. Mirrors the persistence
// approach used by ThemeProvider (ats-theme).

import { useCallback, useEffect, useState } from "react"

const STORAGE_KEY = "ats-sidebar-collapsed"

function getStoredCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1"
  } catch {
    // storage unavailable
    return false
  }
}

function persist(collapsed: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0")
  } catch {
    // ignore
  }
}

export function useSidebarCollapse() {
  const [collapsed, setCollapsed] = useState<boolean>(getStoredCollapsed)

  const set = useCallback((next: boolean) => {
    setCollapsed(next)
    persist(next)
  }, [])

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev
      persist(next)
      return next
    })
  }, [])

  // Keep storage in sync if state is changed externally.
  useEffect(() => {
    persist(collapsed)
  }, [collapsed])

  return { collapsed, set, toggle }
}
