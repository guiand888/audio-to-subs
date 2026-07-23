import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { WantedListResponse, WantedScope } from "@/lib/types"

interface WantedFilters {
  item_type?: "all" | "movie" | "episode"
  language?: string
  search?: string
  // Display filter over the already-synced full library - never narrows
  // what a refresh re-syncs (see WantedPage's handleRefresh).
  scope?: WantedScope
  page?: number
  page_size?: number
  has_job?: boolean
}

export function useWanted(filters: WantedFilters = {}) {
  const params = new URLSearchParams()
  if (filters.item_type) params.set("item_type", filters.item_type)
  if (filters.language) params.set("language", filters.language)
  if (filters.search) params.set("search", filters.search)
  if (filters.scope) params.set("scope", filters.scope)
  if (filters.page !== undefined) params.set("page", String(filters.page))
  if (filters.page_size !== undefined) params.set("page_size", String(filters.page_size))
  if (filters.has_job !== undefined) params.set("has_job", String(filters.has_job))

  const qs = params.toString()
  const url = qs ? `/api/wanted?${qs}` : "/api/wanted"

  return useQuery({
    queryKey: ["wanted", filters],
    queryFn: () => api.get<WantedListResponse>(url),
    staleTime: 30_000,
  })
}
