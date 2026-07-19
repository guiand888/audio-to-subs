import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { GlobalLogsResponse, LogsFilters } from "@/lib/types"

interface UseLogsOptions {
  filters: LogsFilters
  autoRefresh?: boolean
  refreshInterval?: number
}

// Normalise a local datetime input value to an unambiguous UTC ISO string
// for the backend, which compares `since`/`until` against UTC timestamps.
// A value already carrying an offset/Z is passed through unchanged.
function toUtcIso(value: string): string {
  const ms = Date.parse(value)
  if (isNaN(ms)) return value
  return new Date(ms).toISOString()
}

export function useLogs({
  filters,
  autoRefresh = true,
  refreshInterval = 10000,
}: UseLogsOptions) {
  // Build query string from filters
  const params = new URLSearchParams()
  if (filters.level_filter) params.set("level_filter", filters.level_filter)
  if (filters.job_id) params.set("job_id", filters.job_id)
  if (filters.since) params.set("since", toUtcIso(filters.since))
  if (filters.until) params.set("until", toUtcIso(filters.until))
  params.set("limit", String(filters.limit || 50))
  params.set("offset", String(filters.offset || 0))

  return useQuery({
    queryKey: ["logs", filters],
    queryFn: () => api.get<GlobalLogsResponse>(`/api/logs?${params.toString()}`),
    staleTime: 5000, // Shorter stale time for logs
    refetchInterval: autoRefresh ? refreshInterval : undefined,
  })
}
