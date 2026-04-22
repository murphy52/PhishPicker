import { render, screen, waitFor } from "@testing-library/react";
import { SlotAltsModal } from "./SlotAltsModal";

function mockSlotResponse(overrides: object = {}) {
  return {
    slot_idx: 5,
    set_number: "1",
    position: 5,
    state: "predicted",
    top_k: [
      { song_id: 10, name: "Reba", probability: 0.25, score: 5, rank: 1 },
      { song_id: 11, name: "Bathtub Gin", probability: 0.15, score: 3, rank: 2 },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => mockSlotResponse(),
  }) as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

test("renders nothing when slotIdx is null", () => {
  render(
    <SlotAltsModal showId="abc" slotIdx={null} onClose={() => {}} onPick={() => {}} />,
  );
  expect(screen.queryByTestId("slot-alts-modal")).not.toBeInTheDocument();
});

test("fetches slot alternatives when slotIdx is set", async () => {
  render(
    <SlotAltsModal showId="abc" slotIdx={5} onClose={() => {}} onPick={() => {}} />,
  );
  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalled();
    const url = (global.fetch as unknown as { mock: { calls: unknown[][] } }).mock
      .calls[0][0] as string;
    expect(url).toContain("/api/live/show/abc/slot/5/alternatives");
  });
});

test("displays candidate names from response", async () => {
  render(
    <SlotAltsModal showId="abc" slotIdx={5} onClose={() => {}} onPick={() => {}} />,
  );
  expect(await screen.findByText("Reba")).toBeInTheDocument();
  expect(screen.getByText("Bathtub Gin")).toBeInTheDocument();
});

test("clicking a candidate calls onPick with the song", async () => {
  const onPick = vi.fn();
  render(
    <SlotAltsModal showId="abc" slotIdx={5} onClose={() => {}} onPick={onPick} />,
  );
  const candidate = await screen.findByText("Reba");
  candidate.click();
  expect(onPick).toHaveBeenCalledWith(
    expect.objectContaining({ song_id: 10, name: "Reba" }),
  );
});

test("clicking close calls onClose", async () => {
  const onClose = vi.fn();
  render(
    <SlotAltsModal showId="abc" slotIdx={5} onClose={onClose} onPick={() => {}} />,
  );
  const close = await screen.findByLabelText("Close alternatives");
  close.click();
  expect(onClose).toHaveBeenCalled();
});
