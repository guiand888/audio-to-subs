import { QueryClient } from "@tanstack/react-query"

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        // Don't retry on 401 (auth) or 404
        if (error instanceof Error && "status" in error) {
          const status = (error as { status: number }).status
          if (status === 401 || status === 404) return false
        }
        return failureCount < 2
      },
    },
  },
})
