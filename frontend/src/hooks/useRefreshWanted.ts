import { useMutation } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { WantedRefreshRequest, WantedRefreshResponse } from "@/lib/types"

// Note: no onSuccess invalidate of ["wanted"] here. The POST returns
// status:"started" before the background task has written anything, so an
// immediate refetch would observe stale data and mask the real update that
// arrives with refresh_done. Callers (useWantedRefresh) invalidate at the
// correct moment: after the SSE stream confirms completion.
export function useRefreshWanted() {
  return useMutation({
    mutationFn: (request: WantedRefreshRequest) =>
      api.post<WantedRefreshResponse>("/api/wanted/refresh", request),
  })
}
