import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import manifest from "@/app/manifest";
import { RotateGuard } from "./RotateGuard";

test("renders the rotate-to-portrait message", () => {
  render(<RotateGuard />);
  expect(screen.getByText(/rotate to portrait/i)).toBeInTheDocument();
});

test("carries the .rotate-guard class that CSS toggles by orientation", () => {
  render(<RotateGuard />);
  // The class is the hook globals.css uses to hide/show it; without it the
  // guard would always be visible.
  expect(screen.getByTestId("rotate-guard")).toHaveClass("rotate-guard");
});

test("manifest locks the installed PWA to portrait", () => {
  expect(manifest().orientation).toBe("portrait");
});
