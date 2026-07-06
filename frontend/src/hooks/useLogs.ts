import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { GlobalLogsResponse, LogsFilters } from "@/lib/types"

interface UseLogsOptions {
  filters: LogsFilters
  autoRefresh?: boolean
  refreshInterval?: number
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
  if (filters.since) params.set("since", filters.since)
  if (filters.until) params.set("until", filters.until)
  params.set("limit", String(filters.limit || 50))
  params.set("offset", String(filters.offset || 0))

  return useQuery({
    queryKey: ["logs", filters],
    queryFn: () => api.get<GlobalLogsResponse>(`/api/logs?${params.toString()}`),
    staleTime: 5000, // Shorter stale time for logs
    refetchInterval: autoRefresh ? refreshInterval : undefined,
  })
}
