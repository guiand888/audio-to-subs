import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"
import type { SettingsOut } from "@/lib/types"

// An invalid/empty timezone resolves to the browser's local IANA zone so that
// times are correct out of the box before the user picks a zone explicitly.
export const DEFAULT_TIMEZONE = "UTC"

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || DEFAULT_TIMEZONE
  } catch {
    return DEFAULT_TIMEZONE
  }
}

/**
 * Resolve the effective display timezone: the saved setting if set, otherwise
 * the browser's detected IANA zone (so a first-time user sees local time
 * before they configure anything).
 */
export function resolveTimezone(saved: string | null | undefined): string {
  if (saved && saved.trim()) return saved
  return browserTimezone()
}

/**
 * Read the persisted timezone setting via the shared settings query cache.
 * Returns null while settings are loading so callers can fall back.
 */
export function useTimezoneSetting(): string | null {
  const { data } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsOut>("/api/settings"),
    staleTime: 60_000,
  })
  if (!data) return null
  return resolveTimezone(data.timezone)
}

interface FormatOptions {
  timeZone?: string
  dateStyle?: "full" | "long" | "medium" | "short"
  timeStyle?: "full" | "long" | "medium" | "short"
}

function toMillis(value: string | Date): number | null {
  if (value instanceof Date) return isNaN(value.getTime()) ? null : value.getTime()
  const ms = Date.parse(value)
  return isNaN(ms) ? null : ms
}

function format(value: string | Date | null | undefined, opts: FormatOptions): string {
  if (value === null || value === undefined) return "—"
  const ms = toMillis(value)
  if (ms === null) return typeof value === "string" ? value : "—"
  const timeZone = opts.timeZone || browserTimezone()
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone,
      dateStyle: opts.dateStyle,
      timeStyle: opts.timeStyle,
    }).format(new Date(ms))
  } catch {
    return new Date(ms).toISOString()
  }
}

// Full date + time, e.g. "Jul 10, 2026, 2:55 PM".
export function formatDateTime(
  value: string | Date | null | undefined,
  timeZone?: string,
): string {
  return format(value, {
    timeZone,
    dateStyle: "medium",
    timeStyle: "medium",
  })
}

// Date only, e.g. "Jul 10, 2026".
export function formatDate(
  value: string | Date | null | undefined,
  timeZone?: string,
): string {
  return format(value, { timeZone, dateStyle: "medium" })
}

// Time only, e.g. "2:55:25 PM".
export function formatTime(
  value: string | Date | null | undefined,
  timeZone?: string,
): string {
  return format(value, { timeZone, timeStyle: "medium" })
}

/**
 * The list of IANA timezone identifiers supported by the runtime, grouped by
 * region prefix (the part before the first "/") for the settings picker.
 * Falls back to a small common set when Intl.supportedValuesOf is unavailable.
 */
export function listTimezones(): { region: string; zones: string[] }[] {
  let zones: string[]
  try {
    // Intl.supportedValuesOf is available in modern browsers/Node.
    const supported = (Intl as unknown as {
      supportedValuesOf?: (key: string) => string[]
    }).supportedValuesOf?.("timeZone")
    zones = supported && supported.length > 0 ? [...supported] : []
  } catch {
    zones = []
  }
  if (zones.length === 0) {
    zones = ["UTC", "Europe/Paris", "Europe/London", "America/New_York", "America/Los_Angeles", "Asia/Tokyo"]
  }
  const groups = new Map<string, string[]>()
  for (const z of zones) {
    const region = z.includes("/") ? z.slice(0, z.indexOf("/")) : "Other"
    const arr = groups.get(region)
    if (arr) arr.push(z)
    else groups.set(region, [z])
  }
  return [...groups.entries()]
    .map(([region, zs]) => ({ region, zones: zs.sort() }))
    .sort((a, b) => a.region.localeCompare(b.region))
}
