import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { JobCreate, JobListResponse, JobResponse } from "@/lib/types"

interface JobsFilters {
  status_filter?: string
  source_filter?: string
  limit?: number
  offset?: number
}

export function useJobs(filters: JobsFilters = {}) {
  const params = new URLSearchParams()
  if (filters.status_filter) params.set("status_filter", filters.status_filter)
  if (filters.source_filter) params.set("source_filter", filters.source_filter)
  if (filters.limit !== undefined) params.set("limit", String(filters.limit))
  if (filters.offset !== undefined) params.set("offset", String(filters.offset))

  const qs = params.toString()
  const url = qs ? `/api/jobs?${qs}` : "/api/jobs"

  return useQuery({
    queryKey: ["jobs", filters],
    queryFn: () => api.get<JobListResponse>(url),
    staleTime: 10_000,
  })
}

export function useCreateJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (job: JobCreate) => api.post<JobResponse>("/api/jobs", job),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["jobs"] })
    },
  })
}

export function useCancelJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => api.post<JobResponse>(`/api/jobs/${jobId}/cancel`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["jobs"] })
    },
  })
}
