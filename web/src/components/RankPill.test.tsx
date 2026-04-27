import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { RankPill } from "./RankPill";

test("renders rank with green class for rank 1", () => {
  render(<RankPill rank={1} />);
  const el = screen.getByTestId("rank-pill");
  expect(el).toHaveTextContent("#1");
  expect(el.className).toMatch(/green/);
});

test("renders yellow for ranks 2-5", () => {
  render(<RankPill rank={3} />);
  expect(screen.getByTestId("rank-pill").className).toMatch(/yellow/);
});

test("renders orange for ranks 6-20", () => {
  render(<RankPill rank={15} />);
  expect(screen.getByTestId("rank-pill").className).toMatch(/orange/);
});

test("renders red for ranks 21+", () => {
  render(<RankPill rank={42} />);
  expect(screen.getByTestId("rank-pill").className).toMatch(/red/);
});

test("renders dash with grey class when rank is null", () => {
  render(<RankPill rank={null} />);
  const el = screen.getByTestId("rank-pill");
  expect(el).toHaveTextContent("—");
  expect(el.className).toMatch(/(neutral|gray|grey)/);
});
