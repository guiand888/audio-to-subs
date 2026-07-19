import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { LogsPage } from "./LogsPage"

const EMPTY_LOGS = { logs: [], total: 0 }

vi.mock("@/lib/api", () => ({
  api: { get: () => Promise.resolve(EMPTY_LOGS) },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe("LogsPage", () => {
  it("opens the Level filter without throwing Radix empty-value error", async () => {
    const user = userEvent.setup()
    render(<LogsPage />, { wrapper })

    // Before the fix, Radix throws when it encounters <SelectItem value="">.
    const [levelTrigger] = await screen.findAllByRole("combobox")
    await user.click(levelTrigger)

    expect(screen.getAllByText("All levels").length).toBeGreaterThan(0)
  })
})
