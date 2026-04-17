import { GET, POST, DELETE } from "./route";
import { NextRequest } from "next/server";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockResolvedValue({
    status: 200,
    json: async () => ({ ok: true }),
  });
});

test("proxies GET to backend with correct URL", async () => {
  const req = new NextRequest("http://localhost/api/songs");
  const params = Promise.resolve({ path: ["songs"] });

  const res = await GET(req, { params });

  expect(mockFetch).toHaveBeenCalledWith(
    "http://api:8000/songs",
    expect.objectContaining({ method: "GET" }),
  );
  expect(res.status).toBe(200);
});

test("proxies nested path to backend", async () => {
  const req = new NextRequest("http://localhost/api/predict/show1");
  const params = Promise.resolve({ path: ["predict", "show1"] });

  await GET(req, { params });

  expect(mockFetch).toHaveBeenCalledWith(
    "http://api:8000/predict/show1",
    expect.anything(),
  );
});

test("forwards query string to backend", async () => {
  const req = new NextRequest(
    "http://localhost/api/predict/show1?top_n=5",
  );
  const params = Promise.resolve({ path: ["predict", "show1"] });

  await GET(req, { params });

  expect(mockFetch).toHaveBeenCalledWith(
    "http://api:8000/predict/show1?top_n=5",
    expect.anything(),
  );
});

test("proxies POST request with body", async () => {
  const body = JSON.stringify({ show_date: "2024-01-01" });
  const req = new NextRequest("http://localhost/api/live/show", {
    method: "POST",
    body,
  });
  const params = Promise.resolve({ path: ["live", "show"] });

  await POST(req, { params });

  expect(mockFetch).toHaveBeenCalledWith(
    "http://api:8000/live/show",
    expect.objectContaining({ method: "POST", body }),
  );
});

test("forwards non-200 status from backend", async () => {
  mockFetch.mockResolvedValue({
    status: 404,
    json: async () => ({ detail: "not found" }),
  });
  const req = new NextRequest("http://localhost/api/songs/999");
  const params = Promise.resolve({ path: ["songs", "999"] });

  const res = await GET(req, { params });

  expect(res.status).toBe(404);
});

test("proxies DELETE request", async () => {
  const req = new NextRequest("http://localhost/api/live/song/last?show_id=s1", {
    method: "DELETE",
  });
  const params = Promise.resolve({ path: ["live", "song", "last"] });

  await DELETE(req, { params });

  expect(mockFetch).toHaveBeenCalledWith(
    "http://api:8000/live/song/last?show_id=s1",
    expect.objectContaining({ method: "DELETE" }),
  );
});
