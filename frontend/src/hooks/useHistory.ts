import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { HistoryFilters, HistoryResponse } from "@/lib/types"

// Normalise a local datetime input value to an unambiguous UTC ISO string
// for the backend, which compares `since`/`until` against UTC timestamps.
// A value already carrying an offset/Z is passed through unchanged.
function toUtcIso(value: string): string {
  const ms = Date.parse(value)
  if (isNaN(ms)) return value
  return new Date(ms).toISOString()
}

export function useHistory(filters: HistoryFilters) {
  // Build query string from filters
  const params = new URLSearchParams()
  if (filters.status_filter?.length) {
    filters.status_filter.forEach((s) => params.append("status_filter", s))
  }
  if (filters.source_filter) params.set("source_filter", filters.source_filter)
  if (filters.language_filter) params.set("language_filter", filters.language_filter)
  if (filters.since) params.set("since", toUtcIso(filters.since))
  if (filters.until) params.set("until", toUtcIso(filters.until))
  params.set("limit", String(filters.limit || 20))
  params.set("offset", String(filters.offset || 0))

  return useQuery({
    queryKey: ["history", filters],
    queryFn: () => api.get<HistoryResponse>(`/api/history?${params.toString()}`),
    staleTime: 30_000,
  })
}
