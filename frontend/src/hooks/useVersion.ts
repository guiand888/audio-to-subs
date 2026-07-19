import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { APP_VERSION, IS_DEV_BUILD } from "@/lib/version"

interface VersionResponse {
  version: string
}

/**
 * Resolve the version to display.
 *
 * Prefers the value baked into the bundle at build time (APP_VERSION) — no
 * network, no layout shift. When that's a local "dev" build we fall back to
 * the backend's GET /api/version, which is the authoritative runtime source
 * of truth for the actually-running deployment.
 */
export function useVersion(): string {
  const { data } = useQuery({
    queryKey: ["version"],
    queryFn: () => api.get<VersionResponse>("/api/version"),
    staleTime: Infinity,
    retry: false,
    // Only hit the endpoint when the baked value is a dev placeholder.
    enabled: IS_DEV_BUILD,
  })

  if (!IS_DEV_BUILD) return APP_VERSION
  return data?.version ?? APP_VERSION
}
