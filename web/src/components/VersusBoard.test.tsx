import { render, screen } from "@testing-library/react";
import { VersusBoard } from "./VersusBoard";

const versus = {
  picker_total: 22,
  phish_total: 40,
  leader: "phish" as const,
  per_song: [
    { index: 0, song_id: 1, name: "Tweezer", side: "picker" as const, points: 10, reason: "exact" },
    { index: 1, song_id: 2, name: "Icculus", side: "phish" as const, points: 13, reason: "absent-bustout" },
  ],
};

test("shows both totals and who's leading", () => {
  render(<VersusBoard versus={versus} />);
  expect(screen.getByTestId("vs-picker-total")).toHaveTextContent("22");
  expect(screen.getByTestId("vs-phish-total")).toHaveTextContent("40");
  expect(screen.getByTestId("vs-leader")).toHaveTextContent(/phish/i);
});

test("lists each played song on its scoring side", () => {
  render(<VersusBoard versus={versus} />);
  const tweezer = screen.getByText("Tweezer").closest("[data-side]");
  expect(tweezer).toHaveAttribute("data-side", "picker");
  const icculus = screen.getByText("Icculus").closest("[data-side]");
  expect(icculus).toHaveAttribute("data-side", "phish");
});

test("final board says who won, not who leads", () => {
  render(<VersusBoard versus={versus} final />);
  expect(screen.getByTestId("vs-leader")).toHaveTextContent("Phish wins");
});

test("final board calls a tie", () => {
  render(
    <VersusBoard
      versus={{ ...versus, picker_total: 40, leader: "tie" }}
      final
    />,
  );
  expect(screen.getByTestId("vs-leader")).toHaveTextContent("Tie");
});

test("final board names PhishPicker the winner", () => {
  render(
    <VersusBoard
      versus={{ ...versus, picker_total: 44, leader: "picker" }}
      final
    />,
  );
  expect(screen.getByTestId("vs-leader")).toHaveTextContent("PhishPicker wins");
});
