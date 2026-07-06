import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { WantedRefreshRequest, WantedRefreshResponse } from "@/lib/types"

export function useRefreshWanted() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (request: WantedRefreshRequest) =>
      api.post<WantedRefreshResponse>("/api/wanted/refresh", request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["wanted"] })
    },
  })
}
