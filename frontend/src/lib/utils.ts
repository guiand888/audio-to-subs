import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Locale-aware "natural" collator: compares embedded numbers by magnitude
// ("Episode 2" < "Episode 10" < "Episode 100") while staying case- and
// accent-insensitive. Use for any user-facing title/name ordering.
export const naturalCollator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
})

export function naturalCompare(a: string, b: string): number {
  return naturalCollator.compare(a, b)
}

// Format cost as USD
export function formatCost(cost: number | null | undefined): string {
  if (cost === null || cost === undefined) return "—"
  if (cost === 0) return "$0.00"
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  if (cost < 1) return `$${cost.toFixed(2)}`
  return `$${cost.toFixed(2)}`
}

// Format duration as human-readable string
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—"
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (minutes < 60) return `${minutes}m ${secs}s`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return `${hours}h ${mins}m`
}
