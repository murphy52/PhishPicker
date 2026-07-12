import { render, screen } from "@testing-library/react";
import type { ShowMeta } from "@/lib/score";
import { ShowMetaBar } from "./ShowMetaBar";

const base: ShowMeta = {
  show_date: "2026-07-11",
  venue: "Ruoff Music Center",
  city: "Noblesville",
  state: "IN",
  run_position: 2,
  run_length: 2,
};

test("renders venue, date, and city/state", () => {
  render(<ShowMetaBar show={base} />);
  expect(screen.getByText("Ruoff Music Center")).toBeInTheDocument();
  expect(screen.getByText(/Jul 11, 2026/)).toBeInTheDocument();
  expect(screen.getByText(/Noblesville, IN/)).toBeInTheDocument();
});

test("shows the residency run badge for a multi-night run", () => {
  render(<ShowMetaBar show={base} />);
  expect(screen.getByTestId("run-badge")).toHaveTextContent("Run 2/2");
});

test("hides the run badge for a one-off show", () => {
  render(
    <ShowMetaBar show={{ ...base, run_position: null, run_length: null }} />,
  );
  expect(screen.queryByTestId("run-badge")).toBeNull();
});

test("date is timezone-safe (no day-before drift)", () => {
  render(<ShowMetaBar show={base} />);
  // A naive `new Date("2026-07-11")` in a negative-offset TZ renders Jul 10.
  expect(screen.queryByText(/Jul 10/)).toBeNull();
});

test("degrades when the venue is unresolved", () => {
  render(
    <ShowMetaBar
      show={{ ...base, venue: "", city: "", state: "", run_position: null, run_length: null }}
    />,
  );
  expect(screen.getByText(/Jul 11, 2026/)).toBeInTheDocument();
});
