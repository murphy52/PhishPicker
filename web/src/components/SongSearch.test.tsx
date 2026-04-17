import { render, screen, fireEvent } from "@testing-library/react";
import { SongSearch } from "./SongSearch";

const songs = [
  { song_id: 1, name: "You Enjoy Myself", original_artist: null },
  { song_id: 2, name: "Tweezer", original_artist: null },
  { song_id: 3, name: "Wilson", original_artist: null },
  { song_id: 4, name: "Weekapaug Groove", original_artist: null },
];

test("renders search input", () => {
  render(<SongSearch songs={songs} onSelect={() => {}} />);
  expect(screen.getByRole("textbox")).toBeInTheDocument();
});

test("shows no results when no query", () => {
  render(<SongSearch songs={songs} onSelect={() => {}} />);
  expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
});

test("shows matching songs when query entered", () => {
  render(<SongSearch songs={songs} onSelect={() => {}} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "twee" } });
  expect(screen.getByText("Tweezer")).toBeInTheDocument();
});

test("hides non-matching songs when query entered", () => {
  render(<SongSearch songs={songs} onSelect={() => {}} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "twee" } });
  expect(screen.queryByText("Wilson")).not.toBeInTheDocument();
});

test("calls onSelect with the clicked song", () => {
  const onSelect = vi.fn();
  render(<SongSearch songs={songs} onSelect={onSelect} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "twee" } });
  fireEvent.click(screen.getByText("Tweezer"));
  expect(onSelect).toHaveBeenCalledWith(songs[1]);
});

test("clears results when query is cleared", () => {
  render(<SongSearch songs={songs} onSelect={() => {}} />);
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "twee" } });
  fireEvent.change(input, { target: { value: "" } });
  expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
});

test("matches partial song name case-insensitively", () => {
  render(<SongSearch songs={songs} onSelect={() => {}} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "ENJOY" } });
  expect(screen.getByText("You Enjoy Myself")).toBeInTheDocument();
});
