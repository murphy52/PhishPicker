import { render, screen, fireEvent } from "@testing-library/react";
import type { LiveSong } from "@/lib/liveShow";
import { PlayedStrip } from "./PlayedStrip";

const userSongs: LiveSong[] = [
  { song_id: 1, name: "Chalk Dust Torture", set_number: "1", source: "user" },
  { song_id: 2, name: "Tweezer", set_number: "1", source: "user" },
];

test("renders each un-reconciled song", () => {
  render(<PlayedStrip songs={userSongs} onUndo={() => {}} />);
  expect(screen.getByText("Chalk Dust Torture")).toBeInTheDocument();
  expect(screen.getByText("Tweezer")).toBeInTheDocument();
});

test("renders nothing when no songs played", () => {
  render(<PlayedStrip songs={[]} onUndo={() => {}} />);
  expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
});

test("renders nothing when every song is reconciled", () => {
  const reconciled: LiveSong[] = userSongs.map((s) => ({ ...s, source: "phishnet" }));
  render(<PlayedStrip songs={reconciled} onUndo={() => {}} />);
  expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
});

test("hides reconciled songs but shows un-reconciled ones", () => {
  const mixed: LiveSong[] = [
    { song_id: 1, name: "Chalk Dust Torture", set_number: "1", source: "phishnet" },
    { song_id: 2, name: "Tweezer", set_number: "1", source: "user" },
  ];
  render(<PlayedStrip songs={mixed} onUndo={() => {}} />);
  expect(screen.queryByText("Chalk Dust Torture")).not.toBeInTheDocument();
  expect(screen.getByText("Tweezer")).toBeInTheDocument();
});

test("calls onUndo when undo button clicked", () => {
  const onUndo = vi.fn();
  render(<PlayedStrip songs={userSongs} onUndo={onUndo} />);
  fireEvent.click(screen.getByRole("button", { name: /undo/i }));
  expect(onUndo).toHaveBeenCalledTimes(1);
});

test("shows only one undo button (last un-reconciled song)", () => {
  render(<PlayedStrip songs={userSongs} onUndo={() => {}} />);
  expect(screen.getAllByRole("button", { name: /undo/i })).toHaveLength(1);
});
