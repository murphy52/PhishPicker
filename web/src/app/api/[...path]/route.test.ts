import { GET, POST, DELETE, PUT } from "./route";
import { NextRequest } from "next/server";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function mockOk(body = {}) {
  return {
    status: 200,
    headers: new Headers({ "content-type": "application/json" }),
    arrayBuffer: async () => new TextEncoder().encode(JSON.stringify(body)).buffer,
    getSetCookie: () => [] as string[],
  };
}

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockResolvedValue(mockOk({ ok: true }));
});

test("proxies GET to backend with correct URL", async () => {
  const req = new NextRequest("http://localhost/api/songs");
  const res = await GET(req, { params: Promise.resolve({ path: ["songs"] }) });

  expect(mockFetch).toHaveBeenCalledWith(
    "http://api:8000/songs",
    expect.objectContaining({ method: "GET" }),
  );
  expect(res.status).toBe(200);
});

test("proxies nested path to backend", async () => {
  const req = new NextRequest("http://localhost/api/predict/show1");
  await GET(req, { params: Promise.resolve({ path: ["predict", "show1"] }) });

  expect(mockFetch).toHaveBeenCalledWith("http://api:8000/predict/show1", expect.anything());
});

test("forwards query string to backend", async () => {
  const req = new NextRequest("http://localhost/api/predict/show1?top_n=5");
  await GET(req, { params: Promise.resolve({ path: ["predict", "show1"] }) });

  expect(mockFetch).toHaveBeenCalledWith(
    "http://api:8000/predict/show1?top_n=5",
    expect.anything(),
  );
});

test("proxies POST request with body", async () => {
  const body = JSON.stringify({ show_date: "2024-01-01" });
  const req = new NextRequest("http://localhost/api/live/show", { method: "POST", body });
  await POST(req, { params: Promise.resolve({ path: ["live", "show"] }) });

  expect(mockFetch).toHaveBeenCalledWith(
    "http://api:8000/live/show",
    expect.objectContaining({ method: "POST", body }),
  );
});

test("forwards non-200 status from backend", async () => {
  mockFetch.mockResolvedValue({
    ...mockOk({ detail: "not found" }),
    status: 404,
  });
  const req = new NextRequest("http://localhost/api/songs/999");
  const res = await GET(req, { params: Promise.resolve({ path: ["songs", "999"] }) });

  expect(res.status).toBe(404);
});

test("proxies DELETE request", async () => {
  const req = new NextRequest("http://localhost/api/live/song/last?show_id=s1", {
    method: "DELETE",
  });
  await DELETE(req, { params: Promise.resolve({ path: ["live", "song", "last"] }) });

  expect(mockFetch).toHaveBeenCalledWith(
    "http://api:8000/live/song/last?show_id=s1",
    expect.objectContaining({ method: "DELETE" }),
  );
});

test("strips host header before forwarding to backend", async () => {
  const req = new NextRequest("http://localhost/api/songs", {
    headers: { host: "evil.com", "x-custom": "keep-me" },
  });
  await GET(req, { params: Promise.resolve({ path: ["songs"] }) });

  const [, init] = mockFetch.mock.calls[0] as [string, RequestInit & { headers: Headers }];
  const forwarded = init.headers as Headers;
  expect(forwarded.get("host")).toBeNull();
});

test("supports PUT method", async () => {
  const req = new NextRequest("http://localhost/api/live/show/s1", { method: "PUT" });
  await PUT(req, { params: Promise.resolve({ path: ["live", "show", "s1"] }) });

  expect(mockFetch).toHaveBeenCalledWith(
    "http://api:8000/live/show/s1",
    expect.objectContaining({ method: "PUT" }),
  );
});
