import { render, screen, fireEvent } from "@testing-library/react";
import { AddSongSheet } from "./AddSongSheet";

const songs = [
  { song_id: 1, name: "Chalk Dust Torture" },
  { song_id: 2, name: "Tweezer" },
  { song_id: 3, name: "Wilson" },
];

test("renders open button", () => {
  render(<AddSongSheet songs={songs} onAdd={() => {}} />);
  expect(screen.getByRole("button", { name: /add song/i })).toBeInTheDocument();
});

test("sheet is closed by default", () => {
  render(<AddSongSheet songs={songs} onAdd={() => {}} />);
  expect(screen.queryByPlaceholderText(/search/i)).not.toBeInTheDocument();
});

test("opens sheet when button clicked", () => {
  render(<AddSongSheet songs={songs} onAdd={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: /add song/i }));
  expect(screen.getByRole("textbox")).toBeInTheDocument();
});

test("calls onAdd with song when result clicked", () => {
  const onAdd = vi.fn();
  render(<AddSongSheet songs={songs} onAdd={onAdd} />);
  fireEvent.click(screen.getByRole("button", { name: /add song/i }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "twee" } });
  fireEvent.click(screen.getByText("Tweezer"));
  expect(onAdd).toHaveBeenCalledWith(songs[1]);
});

test("closes sheet after song selected", () => {
  render(<AddSongSheet songs={songs} onAdd={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: /add song/i }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "twee" } });
  fireEvent.click(screen.getByText("Tweezer"));
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});
