import { render, screen } from "@testing-library/react";
import { ComboMeter } from "./ComboMeter";

function litCount() {
  return screen
    .getAllByTestId("combo-segment")
    .filter((el) => el.getAttribute("data-lit") === "true").length;
}

test("cold meter: nothing lit, next catch pays ×1", () => {
  render(<ComboMeter streak={0} />);
  expect(litCount()).toBe(0);
  expect(screen.getByTestId("combo-mult")).toHaveTextContent("×1");
});

test("unlit bolts are visually dimmed (emoji ignores CSS color)", () => {
  render(<ComboMeter streak={1} />);
  const segs = screen.getAllByTestId("combo-segment");
  expect(segs[0].className).not.toContain("grayscale");
  expect(segs[1].className).toContain("grayscale");
  expect(segs[2].className).toContain("grayscale");
});

test("streak 1: one bolt, next catch ×1.5", () => {
  render(<ComboMeter streak={1} />);
  expect(litCount()).toBe(1);
  expect(screen.getByTestId("combo-mult")).toHaveTextContent("×1.5");
});

test("streak 4: capped at three bolts, ×2", () => {
  render(<ComboMeter streak={4} />);
  expect(litCount()).toBe(3);
  expect(screen.getByTestId("combo-mult")).toHaveTextContent("×2");
});

test("closed show: no forward 'next catch' tease", () => {
  render(<ComboMeter streak={1} closed />);
  const mult = screen.getByTestId("combo-mult");
  expect(mult).not.toHaveTextContent(/next catch/i);
});

test("closed show with a real combo notes the multiplier it earned", () => {
  render(<ComboMeter streak={2} closed />);
  const mult = screen.getByTestId("combo-mult");
  expect(mult).toHaveTextContent("×1.5");
  expect(mult).not.toHaveTextContent(/next catch/i);
});

test("closed show still lights the segments for the achieved streak", () => {
  render(<ComboMeter streak={2} closed />);
  expect(litCount()).toBe(2);
});

test("a streak drop triggers the drain", () => {
  const { rerender } = render(<ComboMeter streak={3} />);
  expect(screen.getByTestId("combo-meter")).toHaveAttribute(
    "data-draining",
    "false",
  );
  rerender(<ComboMeter streak={0} />);
  expect(screen.getByTestId("combo-meter")).toHaveAttribute(
    "data-draining",
    "true",
  );
});
