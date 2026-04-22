import { describe, it, expect } from "vitest";
import { hoursUntilShow, showStartUTC, formatCountdown } from "./time";

describe("showStartUTC", () => {
  it("interprets 19:00 local in America/Los_Angeles as the correct UTC moment", () => {
    // 2026-04-23 is PDT (UTC-7). 19:00 PDT = 02:00 UTC next day.
    const utc = showStartUTC("2026-04-23", "19:00", "America/Los_Angeles");
    expect(utc.toISOString()).toBe("2026-04-24T02:00:00.000Z");
  });

  it("interprets 20:00 local in America/New_York as the correct UTC moment", () => {
    // 2026-04-23 is EDT (UTC-4). 20:00 EDT = 00:00 UTC next day.
    const utc = showStartUTC("2026-04-23", "20:00", "America/New_York");
    expect(utc.toISOString()).toBe("2026-04-24T00:00:00.000Z");
  });

  it("handles America/Phoenix (no DST)", () => {
    // Phoenix stays on MST (UTC-7) year-round. 19:00 MST = 02:00 UTC next day.
    const utc = showStartUTC("2026-04-23", "19:00", "America/Phoenix");
    expect(utc.toISOString()).toBe("2026-04-24T02:00:00.000Z");
  });
});

describe("hoursUntilShow", () => {
  it("returns positive hours when show is in the future", () => {
    const now = new Date("2026-04-23T20:00:00.000Z");
    // Show at 19:00 PDT = 02:00 UTC next day → 6h after `now`.
    const h = hoursUntilShow(now, "2026-04-23", "19:00", "America/Los_Angeles");
    expect(h).toBeCloseTo(6, 1);
  });

  it("returns negative hours when show has started", () => {
    const now = new Date("2026-04-24T05:00:00.000Z");
    // 3h after a 02:00 UTC start.
    const h = hoursUntilShow(now, "2026-04-23", "19:00", "America/Los_Angeles");
    expect(h).toBeCloseTo(-3, 1);
  });

  it("returns ~0 at show start", () => {
    const now = new Date("2026-04-24T02:00:00.000Z");
    const h = hoursUntilShow(now, "2026-04-23", "19:00", "America/Los_Angeles");
    expect(Math.abs(h)).toBeLessThan(0.01);
  });
});

describe("formatCountdown", () => {
  it("formats days and hours for > 48h", () => {
    expect(formatCountdown(76.5)).toBe("in 3d 4h");
  });

  it("formats hours and minutes between 1h and 24h", () => {
    expect(formatCountdown(5.2)).toBe("in 5h 12m");
  });

  it("formats minutes only under 1h", () => {
    expect(formatCountdown(0.7)).toBe("in 42m");
  });

  it("reports 'starting now' at near-zero", () => {
    expect(formatCountdown(0)).toBe("starting now");
    expect(formatCountdown(0.005)).toBe("starting now");
  });

  it("formats past times with 'started … ago'", () => {
    expect(formatCountdown(-1.5)).toBe("started 1h 30m ago");
    expect(formatCountdown(-0.5)).toBe("started 30m ago");
  });
});
