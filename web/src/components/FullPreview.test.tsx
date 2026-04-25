import { render, screen, fireEvent } from "@testing-library/react";
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

function renderPreview(props: Partial<React.ComponentProps<typeof FullPreview>> = {}) {
  return render(
    <FullPreview
      slots={props.slots ?? []}
      currentSet={props.currentSet ?? "1"}
      onSlotClick={props.onSlotClick ?? (() => {})}
      onSetChange={props.onSetChange ?? (() => {})}
      loading={props.loading}
    />,
  );
}

test("renders skeleton when loading with no slots", () => {
  renderPreview({ loading: true });
  expect(screen.getByTestId("preview-skeleton")).toBeInTheDocument();
  expect(screen.queryByTestId("slot")).not.toBeInTheDocument();
});

test("skeleton is hidden once data arrives", () => {
  renderPreview({ slots: [slot(1, "1", 1)], loading: true });
  expect(screen.queryByTestId("preview-skeleton")).not.toBeInTheDocument();
  expect(screen.getAllByTestId("slot")).toHaveLength(1);
});

test("renders one slot element per preview slot", () => {
  const slots: PreviewSlot[] = [slot(1, "1", 1), slot(2, "1", 2), slot(3, "2", 1)];
  renderPreview({ slots });
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
  renderPreview({ slots });
  expect(screen.getByText("Buried Alive")).toBeInTheDocument();
});

test("predicted slots show their top-1 candidate name grayed", () => {
  renderPreview({ slots: [slot(1, "1", 1)] });
  expect(screen.getByText("Chalk Dust Torture")).toBeInTheDocument();
});

test("always renders all three set headers in order, even when empty", () => {
  renderPreview({ slots: [slot(1, "1", 1)] });
  const headers = screen.getAllByTestId("set-header");
  expect(headers.map((h) => h.textContent)).toEqual(["Set 1", "Set 2", "Encore"]);
});

test("the active set header is marked aria-pressed=true", () => {
  renderPreview({ slots: [slot(1, "1", 1)], currentSet: "2" });
  const headers = screen.getAllByTestId("set-header");
  const active = headers.filter((h) => h.getAttribute("aria-pressed") === "true");
  expect(active).toHaveLength(1);
  expect(active[0]).toHaveTextContent("Set 2");
});

test("clicking a set header calls onSetChange with that set key", () => {
  const onSetChange = vi.fn();
  renderPreview({ slots: [slot(1, "1", 1)], currentSet: "1", onSetChange });
  fireEvent.click(screen.getByRole("button", { name: /encore/i }));
  expect(onSetChange).toHaveBeenCalledWith("E");
});

test("clicking a predicted slot calls onSlotClick with its index", () => {
  const onSlotClick = vi.fn();
  renderPreview({ slots: [slot(5, "1", 5)], onSlotClick });
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
  renderPreview({ slots, onSlotClick });
  screen.getByTestId("slot").click();
  expect(onSlotClick).not.toHaveBeenCalled();
});

function enteredSlot(
  opts: { hit_rank?: number | null; pending?: "adding" | "removing" } = {},
): PreviewSlot {
  return {
    slot_idx: 1,
    set_number: "1",
    position: 1,
    state: "entered",
    entered_song: { song_id: 7, name: "Buried Alive" },
    ...opts,
  };
}

test("entered slot with hit_rank=1 renders the bullseye icon", () => {
  renderPreview({ slots: [enteredSlot({ hit_rank: 1 })] });
  expect(screen.getByTestId("hit-rank-bullseye")).toBeInTheDocument();
});

test("entered slot with hit_rank=3 renders the #N chip", () => {
  renderPreview({ slots: [enteredSlot({ hit_rank: 3 })] });
  expect(screen.getByText("#3")).toBeInTheDocument();
  expect(screen.queryByTestId("hit-rank-bullseye")).not.toBeInTheDocument();
});

test("entered slot with hit_rank=null renders an em-dash", () => {
  renderPreview({ slots: [enteredSlot({ hit_rank: null })] });
  expect(screen.getByTestId("hit-rank-miss")).toHaveTextContent("—");
});

test("entered slot in 'adding' pending state suppresses the hit-rank indicator", () => {
  renderPreview({ slots: [enteredSlot({ hit_rank: 1, pending: "adding" })] });
  expect(screen.queryByTestId("hit-rank-bullseye")).not.toBeInTheDocument();
  expect(screen.queryByTestId("hit-rank-miss")).not.toBeInTheDocument();
});

test("entered slot with hit_rank=1 exposes the bullseye aria-label", () => {
  renderPreview({ slots: [enteredSlot({ hit_rank: 1 })] });
  expect(screen.getByLabelText("Top prediction")).toBeInTheDocument();
});

test("entered slot with hit_rank=3 in 'adding' state suppresses the #N chip", () => {
  renderPreview({ slots: [enteredSlot({ hit_rank: 3, pending: "adding" })] });
  expect(screen.queryByText("#3")).not.toBeInTheDocument();
});

function verifiedSlot(
  opts: { slug?: string | null; source?: "user" | "phishnet"; pending?: "adding" } = {},
): PreviewSlot {
  return {
    slot_idx: 1,
    set_number: "1",
    position: 1,
    state: "entered",
    entered_song: {
      song_id: 588,
      name: "The Man Who Stepped Into Yesterday",
      source: opts.source ?? "phishnet",
      slug: opts.slug === undefined ? "the-man-who-stepped-into-yesterday" : opts.slug,
    },
    pending: opts.pending,
  };
}

test("phishnet-verified entered slot links to the phish.net song page", () => {
  renderPreview({ slots: [verifiedSlot()] });
  const link = screen.getByTestId("phishnet-link");
  expect(link).toHaveAttribute(
    "href",
    "https://phish.net/song/the-man-who-stepped-into-yesterday",
  );
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveTextContent("The Man Who Stepped Into Yesterday");
});

test("user-entered (un-reconciled) slot does not render a link", () => {
  renderPreview({ slots: [verifiedSlot({ source: "user" })] });
  expect(screen.queryByTestId("phishnet-link")).not.toBeInTheDocument();
  expect(
    screen.getByText("The Man Who Stepped Into Yesterday"),
  ).toBeInTheDocument();
});

test("phishnet-verified slot without a slug falls back to plain text", () => {
  renderPreview({ slots: [verifiedSlot({ slug: null })] });
  expect(screen.queryByTestId("phishnet-link")).not.toBeInTheDocument();
});

test("optimistic 'adding' slot does not link even if source is phishnet", () => {
  renderPreview({ slots: [verifiedSlot({ pending: "adding" })] });
  expect(screen.queryByTestId("phishnet-link")).not.toBeInTheDocument();
});
