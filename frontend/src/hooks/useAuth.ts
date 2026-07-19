import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, ApiError } from "@/lib/api"
import type { LoginResponse, UserOut } from "@/lib/types"

export function useMe() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: async (): Promise<UserOut | null> => {
      try {
        return await api.get<UserOut>("/api/auth/me")
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
}

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (credentials: { username: string; password: string }) =>
      api.post<LoginResponse>("/api/auth/login", credentials),
    onSuccess: (data) => {
      // Set cache synchronously so AppLayout sees the user before the navigate
      // fires. invalidateQueries() leaves the stale null in place until the
      // background refetch completes, causing the auth guard to redirect back
      // to /login immediately after a successful login.
      queryClient.setQueryData(["auth", "me"], data.user)
    },
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post("/api/auth/logout"),
    onSuccess: () => {
      queryClient.clear()
    },
  })
}
