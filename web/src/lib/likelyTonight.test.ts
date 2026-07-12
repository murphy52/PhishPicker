import { describe, expect, it } from "vitest";
import { barWidthPct } from "./likelyTonight";

describe("barWidthPct", () => {
  it("fills the bar for the top song", () => {
    expect(barWidthPct(0.28, 0.28)).toBe(100);
  });

  it("scales relative to the max", () => {
    expect(barWidthPct(0.14, 0.28)).toBe(50);
  });

  it("keeps a visible floor for tiny probabilities", () => {
    expect(barWidthPct(0.001, 0.28)).toBe(4);
  });

  it("handles a zero max without dividing by zero", () => {
    expect(barWidthPct(0, 0)).toBe(0);
  });
});
