import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

interface VersionResponse {
  version: string
}

/**
 * Resolve the version to display.
 *
 * The version is reported by the backend's GET /api/version, which derives it
 * from the repo-root VERSION file baked into the package at build time. There
 * is no value baked into the frontend bundle, so the UI always fetches it from
 * the running backend — this stays correct regardless of how the app is
 * deployed (compose, Helm, bare install, …).
 */
export function useVersion(): string {
  const { data } = useQuery({
    queryKey: ["version"],
    queryFn: () => api.get<VersionResponse>("/api/version"),
    staleTime: Infinity,
    retry: false,
  })

  return data?.version ?? "unknown"
}
