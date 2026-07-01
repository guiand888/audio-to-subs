import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { HistoryPage } from "./HistoryPage"

const EMPTY_HISTORY = {
  jobs: [],
  stats: {
    total_jobs: 0,
    total_cost_usd: 0,
    total_duration_seconds: 0,
    average_cost_usd: 0,
    average_duration_seconds: 0,
    count_by_status: {},
    count_by_language: {},
    count_by_source: {},
  },
  total: 0,
  limit: 20,
  offset: 0,
}

vi.mock("@/lib/api", () => ({
  api: { get: () => Promise.resolve(EMPTY_HISTORY) },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe("HistoryPage", () => {
  it("opens the Status filter without throwing Radix empty-value error", async () => {
    const user = userEvent.setup()
    render(<HistoryPage />, { wrapper })

    // The filter form renders immediately (not gated by loading state).
    // Before the fix, Radix throws when it encounters <SelectItem value="">.
    const [statusTrigger] = await screen.findAllByRole("combobox")
    await user.click(statusTrigger)

    // The trigger shows the placeholder and the dropdown item shows the label;
    // both contain this text so use getAllByText.
    expect(screen.getAllByText("All statuses").length).toBeGreaterThan(0)
  })

  it("opens the Source filter without throwing Radix empty-value error", async () => {
    const user = userEvent.setup()
    render(<HistoryPage />, { wrapper })

    const triggers = await screen.findAllByRole("combobox")
    await user.click(triggers[1])

    expect(screen.getAllByText("All sources").length).toBeGreaterThan(0)
  })
})
