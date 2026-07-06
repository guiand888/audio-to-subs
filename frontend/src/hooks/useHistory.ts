import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { HistoryFilters, HistoryResponse } from "@/lib/types"

export function useHistory(filters: HistoryFilters) {
  // Build query string from filters
  const params = new URLSearchParams()
  if (filters.status_filter?.length) {
    filters.status_filter.forEach((s) => params.append("status_filter", s))
  }
  if (filters.source_filter) params.set("source_filter", filters.source_filter)
  if (filters.language_filter) params.set("language_filter", filters.language_filter)
  if (filters.since) params.set("since", filters.since)
  if (filters.until) params.set("until", filters.until)
  params.set("limit", String(filters.limit || 20))
  params.set("offset", String(filters.offset || 0))

  return useQuery({
    queryKey: ["history", filters],
    queryFn: () => api.get<HistoryResponse>(`/api/history?${params.toString()}`),
    staleTime: 30_000,
  })
}
