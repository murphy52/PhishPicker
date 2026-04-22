import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ShowHeader, type UpcomingShow } from "./ShowHeader";

const sphere: UpcomingShow = {
  show_id: 1,
  show_date: "2026-04-23",
  venue: "Sphere",
  city: "Las Vegas",
  state: "NV",
  timezone: "America/Los_Angeles",
  start_time_local: "19:00",
};

describe("ShowHeader", () => {
  it("renders venue and location", () => {
    const now = new Date("2026-04-23T20:00:00.000Z"); // 6h before start
    render(<ShowHeader show={sphere} now={now} />);
    expect(screen.getByText("Sphere")).toBeInTheDocument();
    expect(screen.getByText(/Las Vegas, NV/)).toBeInTheDocument();
  });

  it("shows countdown in future-tense when show is upcoming", () => {
    const now = new Date("2026-04-23T20:00:00.000Z"); // 6h before 02:00Z start
    render(<ShowHeader show={sphere} now={now} />);
    expect(screen.getByTestId("show-countdown")).toHaveTextContent("in 6h");
  });

  it("shows past-tense countdown after the show started", () => {
    const now = new Date("2026-04-24T03:30:00.000Z"); // 1.5h after 02:00Z start
    render(<ShowHeader show={sphere} now={now} />);
    expect(screen.getByTestId("show-countdown")).toHaveTextContent(/started .* ago/);
  });

  it("omits location when city and state are empty", () => {
    const show: UpcomingShow = { ...sphere, city: "", state: "" };
    const now = new Date("2026-04-23T20:00:00.000Z");
    render(<ShowHeader show={show} now={now} />);
    expect(screen.queryByText(/,\s*NV/)).not.toBeInTheDocument();
  });
});
