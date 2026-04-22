import { render, screen } from "@testing-library/react";
import { FullPreview } from "./FullPreview";
import type { PreviewSlot } from "@/lib/preview";

function slot(
  idx: number,
  set: string,
  pos: number,
  opts: Partial<PreviewSlot> = {},
): PreviewSlot {
  return {
    slot_idx: idx,
    set_number: set,
    position: pos,
    state: "predicted",
    top_k: [
      { song_id: 1, name: "Chalk Dust Torture", probability: 0.3, score: 3, rank: 1 },
      { song_id: 2, name: "Tweezer", probability: 0.1, score: 1, rank: 2 },
    ],
    ...opts,
  };
}

test("renders one slot element per preview slot", () => {
  const slots: PreviewSlot[] = [slot(1, "1", 1), slot(2, "1", 2), slot(3, "2", 1)];
  render(<FullPreview slots={slots} onSlotClick={() => {}} />);
  expect(screen.getAllByTestId("slot")).toHaveLength(3);
});

test("entered slots show the entered song name", () => {
  const slots: PreviewSlot[] = [
    {
      slot_idx: 1,
      set_number: "1",
      position: 1,
      state: "entered",
      entered_song: { song_id: 7, name: "Buried Alive" },
    },
  ];
  render(<FullPreview slots={slots} onSlotClick={() => {}} />);
  expect(screen.getByText("Buried Alive")).toBeInTheDocument();
});

test("predicted slots show their top-1 candidate name grayed", () => {
  render(<FullPreview slots={[slot(1, "1", 1)]} onSlotClick={() => {}} />);
  expect(screen.getByText("Chalk Dust Torture")).toBeInTheDocument();
});

test("groups slots by set with set labels", () => {
  const slots: PreviewSlot[] = [slot(1, "1", 1), slot(2, "2", 1), slot(3, "E", 1)];
  render(<FullPreview slots={slots} onSlotClick={() => {}} />);
  expect(screen.getByText(/Set 1/i)).toBeInTheDocument();
  expect(screen.getByText(/Set 2/i)).toBeInTheDocument();
  expect(screen.getByText(/Encore/i)).toBeInTheDocument();
});

test("clicking a predicted slot calls onSlotClick with its index", () => {
  const onSlotClick = vi.fn();
  render(<FullPreview slots={[slot(5, "1", 5)]} onSlotClick={onSlotClick} />);
  screen.getByTestId("slot").click();
  expect(onSlotClick).toHaveBeenCalledWith(5);
});

test("entered slots are not clickable", () => {
  const onSlotClick = vi.fn();
  const slots: PreviewSlot[] = [
    {
      slot_idx: 1,
      set_number: "1",
      position: 1,
      state: "entered",
      entered_song: { song_id: 7, name: "Buried Alive" },
    },
  ];
  render(<FullPreview slots={slots} onSlotClick={onSlotClick} />);
  screen.getByTestId("slot").click();
  expect(onSlotClick).not.toHaveBeenCalled();
});
