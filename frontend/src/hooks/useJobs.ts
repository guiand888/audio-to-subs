import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type {
  JobCreate,
  JobLanguagePatch,
  JobListResponse,
  JobResponse,
} from "@/lib/types"

interface JobsFilters {
  status_filter?: string
  source_filter?: string
  limit?: number
  offset?: number
}

export function useJobs(filters: JobsFilters = {}) {
  const { status_filter, source_filter, limit, offset } = filters
  const params = new URLSearchParams()
  if (status_filter) params.set("status_filter", status_filter)
  if (source_filter) params.set("source_filter", source_filter)
  if (limit !== undefined) params.set("limit", String(limit))
  if (offset !== undefined) params.set("offset", String(offset))

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

export function useUpdateJobLanguage() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ jobId, language_code }: { jobId: string } & JobLanguagePatch) =>
      api.patch<JobResponse>(`/api/jobs/${jobId}/language`, { language_code }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["jobs"] })
      void queryClient.invalidateQueries({ queryKey: ["history"] })
    },
  })
}
