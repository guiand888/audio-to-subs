import { describe, it, expect } from "vitest"

import {
  resolveTimezone,
  formatDateTime,
  formatDate,
  formatTime,
  listTimezones,
  DEFAULT_TIMEZONE,
} from "./datetime"

describe("resolveTimezone", () => {
  it("returns the saved timezone when set", () => {
    expect(resolveTimezone("Europe/Paris")).toBe("Europe/Paris")
  })

  it("falls back to a non-empty browser zone when saved is null", () => {
    const tz = resolveTimezone(null)
    // jsdom resolves a real IANA zone; just assert it's non-empty and not
    // the literal sentinel we use for "unset".
    expect(tz.length).toBeGreaterThan(0)
    expect(tz).not.toBe("")
  })

  it("falls back when saved is an empty string", () => {
    expect(resolveTimezone("").length).toBeGreaterThan(0)
  })

  it("falls back when saved is undefined", () => {
    expect(resolveTimezone(undefined).length).toBeGreaterThan(0)
  })
})

describe("formatDateTime", () => {
  // A fixed UTC instant: 2024-07-10T12:00:00Z (noon UTC).
  const UTC_NOON = "2024-07-10T12:00:00Z"

  it("returns '—' for null/undefined", () => {
    expect(formatDateTime(null)).toBe("—")
    expect(formatDateTime(undefined)).toBe("—")
  })

  it("returns the raw value for an unparseable string", () => {
    expect(formatDateTime("not-a-date", "UTC")).toBe("not-a-date")
  })

  it("formats a UTC timestamp in UTC without shifting the wall clock", () => {
    const out = formatDateTime(UTC_NOON, "UTC")
    // The UTC noon instant must render as noon (12) in the UTC zone, and
    // carry the correct calendar date.
    expect(out).toContain("2024")
    expect(out).toMatch(/12[: ]/) // "12:00:00" or "12 PM"-ish
  })

  it("shifts the wall clock for a zone with a non-zero offset", () => {
    // America/New_York is UTC-4 in July (EDT), so noon UTC = 08:00 local
    // (morning -> AM). Asia/Tokyo is UTC+9, so noon UTC = 21:00 local
    // (evening -> PM). The exact hour string depends on the runtime locale
    // (12h vs 24h), so assert the shift direction via AM/PM markers.
    const utc = formatDateTime(UTC_NOON, "UTC")
    const ny = formatDateTime(UTC_NOON, "America/New_York")
    const tokyo = formatDateTime(UTC_NOON, "Asia/Tokyo")

    expect(ny).not.toEqual(utc)
    expect(tokyo).not.toEqual(utc)
    expect(ny).not.toEqual(tokyo)
    // NY is morning, Tokyo is evening relative to UTC noon.
    expect(ny).toMatch(/AM/i)
    expect(tokyo).toMatch(/PM/i)
  })

  it("produces different output for different zones", () => {
    const a = formatDateTime(UTC_NOON, "America/New_York")
    const b = formatDateTime(UTC_NOON, "Asia/Tokyo")
    expect(a).not.toEqual(b)
  })
})

describe("formatDate / formatTime", () => {
  const UTC_NOON = "2024-07-10T12:00:00Z"

  it("formatDate returns '—' for null and a date for a value", () => {
    expect(formatDate(null)).toBe("—")
    expect(formatDate(UTC_NOON, "UTC")).toContain("2024")
  })

  it("formatTime returns '—' for null and a time for a value", () => {
    expect(formatTime(null)).toBe("—")
    expect(formatTime(UTC_NOON, "UTC")).toMatch(/12[: ]/)
  })
})

describe("listTimezones", () => {
  it("returns a non-empty list grouped by region", () => {
    const groups = listTimezones()
    expect(groups.length).toBeGreaterThan(0)
    for (const g of groups) {
      expect(g.region.length).toBeGreaterThan(0)
      expect(g.zones.length).toBeGreaterThan(0)
    }
  })

  it("includes UTC or a well-known zone somewhere", () => {
    const all = listTimezones().flatMap((g) => g.zones)
    // At least one common zone must be present in any modern runtime.
    expect(
      all.includes("UTC") ||
        all.includes("Europe/Paris") ||
        all.includes("America/New_York"),
    ).toBe(true)
  })

  it("is sorted by region name", () => {
    const groups = listTimezones()
    const regions = groups.map((g) => g.region)
    const sorted = [...regions].sort()
    expect(regions).toEqual(sorted)
  })
})

describe("DEFAULT_TIMEZONE", () => {
  it("is UTC", () => {
    expect(DEFAULT_TIMEZONE).toBe("UTC")
  })
})
