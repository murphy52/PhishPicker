import { render, screen, fireEvent } from "@testing-library/react";
import { PlayedStrip } from "./PlayedStrip";

const songs = [
  { song_id: 1, name: "Chalk Dust Torture" },
  { song_id: 2, name: "Tweezer" },
];

test("renders each played song", () => {
  render(<PlayedStrip songs={songs} onUndo={() => {}} />);
  expect(screen.getByText("Chalk Dust Torture")).toBeInTheDocument();
  expect(screen.getByText("Tweezer")).toBeInTheDocument();
});

test("renders nothing when no songs played", () => {
  render(<PlayedStrip songs={[]} onUndo={() => {}} />);
  expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
});

test("calls onUndo when undo button clicked", () => {
  const onUndo = vi.fn();
  render(<PlayedStrip songs={songs} onUndo={onUndo} />);
  fireEvent.click(screen.getByRole("button", { name: /undo/i }));
  expect(onUndo).toHaveBeenCalledTimes(1);
});

test("shows only one undo button (last song only)", () => {
  render(<PlayedStrip songs={songs} onUndo={() => {}} />);
  expect(screen.getAllByRole("button", { name: /undo/i })).toHaveLength(1);
});
