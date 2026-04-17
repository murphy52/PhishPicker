import { searchSongs, getCachedSongs, setCachedSongs } from "@/lib/songs";

const songs = [
  { song_id: 100, name: "Chalk Dust Torture" },
  { song_id: 101, name: "Tweezer" },
  { song_id: 102, name: "You Enjoy Myself" },
  { song_id: 103, name: "Wilson" },
];

// searchSongs

test("returns first 10 songs when query is empty", () => {
  const big = Array.from({ length: 15 }, (_, i) => ({ song_id: i, name: `Song ${i}` }));
  const hits = searchSongs(big, "");
  expect(hits).toHaveLength(10);
});

test("matches by partial name", () => {
  const hits = searchSongs(songs, "chal");
  expect(hits[0].song_id).toBe(100);
});

test("returns empty when no songs match", () => {
  const hits = searchSongs(songs, "zzzzz");
  expect(hits).toHaveLength(0);
});

test("limits results to the limit param", () => {
  const big = Array.from({ length: 50 }, (_, i) => ({ song_id: i, name: `Song ${i}` }));
  expect(searchSongs(big, "", 5)).toHaveLength(5);
});

test("reuses Fuse index when songs array is the same reference", () => {
  // Call twice with same array — should not throw; result should be identical
  const r1 = searchSongs(songs, "twee");
  const r2 = searchSongs(songs, "twee");
  expect(r1).toEqual(r2);
});

// localStorage cache

test("getCachedSongs returns null when no cache entry exists", () => {
  expect(getCachedSongs("2024-01-01")).toBeNull();
});

test("setCachedSongs round-trips through getCachedSongs", () => {
  const snap = "2024-01-02";
  setCachedSongs(snap, songs);
  expect(getCachedSongs(snap)).toEqual(songs);
});

test("setCachedSongs evicts stale snapshot keys", () => {
  const old = "2023-12-01";
  const fresh = "2024-01-03";
  setCachedSongs(old, songs);
  setCachedSongs(fresh, songs);
  expect(getCachedSongs(old)).toBeNull();
  expect(getCachedSongs(fresh)).toEqual(songs);
});
