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

  it("renders Run: N|M when run position/length are present", () => {
    const show: UpcomingShow = { ...sphere, run_position: 6, run_length: 9 };
    const now = new Date("2026-04-25T20:00:00.000Z");
    render(<ShowHeader show={show} now={now} />);
    const badge = screen.getByTestId("run-badge");
    expect(badge).toHaveTextContent("Run: 6|9");
  });

  it("omits the run badge when residency info is missing", () => {
    const now = new Date("2026-04-23T20:00:00.000Z");
    render(<ShowHeader show={sphere} now={now} />);
    expect(screen.queryByTestId("run-badge")).not.toBeInTheDocument();
  });

  it("omits the run badge when only one of position/length is set", () => {
    const show: UpcomingShow = { ...sphere, run_position: 1 }; // length missing
    const now = new Date("2026-04-23T20:00:00.000Z");
    render(<ShowHeader show={show} now={now} />);
    expect(screen.queryByTestId("run-badge")).not.toBeInTheDocument();
  });
});
