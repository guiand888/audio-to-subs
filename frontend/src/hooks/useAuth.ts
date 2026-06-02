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
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["auth", "me"] })
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
