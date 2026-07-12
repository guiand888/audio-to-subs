// Thin fetch wrapper: same-origin /api calls, credentials: "include" (session cookie),
// JSON body/response, throws ApiError on non-2xx.

import type { JobConflictDetail } from "@/lib/types"

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    // M6.g: detail may be a plain human string (legacy) or a structured
    // JobConflictDetail (409 subtitle_exists / job_already_active).
    public readonly detail: string | JobConflictDetail,
  ) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail))
    this.name = "ApiError"
  }

  /** Narrow a 409 conflict detail to a JobConflictDetail, if present. */
  get conflict(): JobConflictDetail | null {
    if (this.status === 409 && typeof this.detail === "object") {
      return this.detail as JobConflictDetail
    }
    return null
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  })

  if (!res.ok) {
    let detail: string | JobConflictDetail = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as {
        detail?: string | JobConflictDetail
      }
      if (body.detail !== undefined) detail = body.detail
    } catch {
      // ignore JSON parse errors on error responses
    }
    throw new ApiError(res.status, detail)
  }

  // 204 No Content
  if (res.status === 204) return undefined as T

  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
}
