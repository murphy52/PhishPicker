import { render, screen } from "@testing-library/react";
import { ScoreTeaser } from "./ScoreTeaser";

test("shows split + combined and links to the scoreboard", () => {
  render(
    <ScoreTeaser
      totals={{
        foresight_total: 120,
        live_total: 195,
        combined: 315,
        ppps: 45,
        hit_counts: {},
      }}
    />,
  );
  const link = screen.getByTestId("score-teaser");
  expect(link).toHaveAttribute("href", "/score");
  expect(screen.getByText("🔮 120")).toBeInTheDocument();
  expect(screen.getByText("⚡ 195")).toBeInTheDocument();
  expect(screen.getByText("315")).toBeInTheDocument();
});
