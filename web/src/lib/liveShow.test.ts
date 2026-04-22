import { renderHook, act } from "@testing-library/react";
import { useLiveShow } from "@/lib/liveShow";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

beforeEach(() => {
  localStorage.clear();
  mockFetch.mockReset();
  mockFetch.mockResolvedValue({
    json: async () => ({ show_id: "test-show-1" }),
  });
});

test("starts with null showId when localStorage is empty", () => {
  const { result } = renderHook(() => useLiveShow());
  expect(result.current.showId).toBeNull();
});

test("starts with existing show_id from localStorage", () => {
  localStorage.setItem("phishpicker:live_show_id", "existing-id");
  const { result } = renderHook(() => useLiveShow());
  expect(result.current.showId).toBe("existing-id");
});

test("startShow sets showId and persists to localStorage", async () => {
  const { result } = renderHook(() => useLiveShow());

  await act(async () => {
    await result.current.startShow("2024-08-15");
  });

  expect(result.current.showId).toBe("test-show-1");
  expect(localStorage.getItem("phishpicker:live_show_id")).toBe("test-show-1");
});

test("clearShow removes showId and resets state", async () => {
  localStorage.setItem("phishpicker:live_show_id", "existing-id");
  const { result } = renderHook(() => useLiveShow());

  act(() => result.current.clearShow());

  expect(result.current.showId).toBeNull();
  expect(localStorage.getItem("phishpicker:live_show_id")).toBeNull();
  expect(result.current.playedSongs).toHaveLength(0);
});

test("addSong appends to playedSongs optimistically", async () => {
  localStorage.setItem("phishpicker:live_show_id", "s1");
  mockFetch.mockResolvedValue({ json: async () => ({ entered_order: 1 }) });
  const { result } = renderHook(() => useLiveShow());

  await act(async () => {
    await result.current.addSong({ song_id: 42, name: "Tweezer" });
  });

  expect(result.current.playedSongs).toHaveLength(1);
  expect(result.current.playedSongs[0].name).toBe("Tweezer");
});

test("undoLast removes the last played song", async () => {
  localStorage.setItem("phishpicker:live_show_id", "s1");
  mockFetch.mockResolvedValue({ json: async () => ({ deleted: true }) });
  const { result } = renderHook(() => useLiveShow());

  await act(async () => {
    await result.current.addSong({ song_id: 1, name: "A" });
    await result.current.addSong({ song_id: 2, name: "B" });
  });
  await act(async () => {
    await result.current.undoLast();
  });

  expect(result.current.playedSongs).toHaveLength(1);
  expect(result.current.playedSongs[0].name).toBe("A");
});

test("undoLast resets currentSet to 1 when list becomes empty", async () => {
  localStorage.setItem("phishpicker:live_show_id", "s1");
  mockFetch.mockResolvedValue({ json: async () => ({}) });
  const { result } = renderHook(() => useLiveShow());

  await act(async () => {
    await result.current.addSong({ song_id: 1, name: "A" });
    await result.current.advanceSet("E");
  });
  expect(result.current.currentSet).toBe("E");

  await act(async () => {
    await result.current.undoLast();
  });

  expect(result.current.playedSongs).toHaveLength(0);
  expect(result.current.currentSet).toBe("1");
});

test("undoLast leaves currentSet alone when list is still non-empty", async () => {
  localStorage.setItem("phishpicker:live_show_id", "s1");
  mockFetch.mockResolvedValue({ json: async () => ({}) });
  const { result } = renderHook(() => useLiveShow());

  await act(async () => {
    await result.current.addSong({ song_id: 1, name: "A" });
    await result.current.advanceSet("2");
    await result.current.addSong({ song_id: 2, name: "B" });
  });
  expect(result.current.currentSet).toBe("2");

  await act(async () => {
    await result.current.undoLast();
  });

  expect(result.current.currentSet).toBe("2");
  expect(result.current.playedSongs).toHaveLength(1);
});

test("advanceSet changes currentSet", async () => {
  localStorage.setItem("phishpicker:live_show_id", "s1");
  mockFetch.mockResolvedValue({ json: async () => ({ updated: true }) });
  const { result } = renderHook(() => useLiveShow());

  await act(async () => {
    await result.current.advanceSet("2");
  });

  expect(result.current.currentSet).toBe("2");
});
