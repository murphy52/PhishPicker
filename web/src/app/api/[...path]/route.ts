import type { NextRequest } from "next/server";

// Must run on Node — Edge Runtime can't reach the docker-internal api:8000.
export const runtime = "nodejs";
// Prevent static optimization; every request must hit FastAPI.
export const dynamic = "force-dynamic";

const API = process.env.API_INTERNAL_URL ?? "http://api:8000";

const STRIP_REQUEST = new Set([
  "host",
  "content-length",
  "accept-encoding",
  "connection",
  "transfer-encoding",
]);

const STRIP_RESPONSE = new Set([
  "content-encoding",
  "content-length",
  "connection",
  "transfer-encoding",
]);

function forwardHeaders(src: Headers, strip: Set<string>): Headers {
  const out = new Headers();
  src.forEach((value, key) => {
    if (!strip.has(key.toLowerCase())) out.append(key, value);
  });
  return out;
}

type Ctx = { params: Promise<{ path: string[] }> };

async function proxy(req: NextRequest, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  const url = `${API}/${path.join("/")}${req.nextUrl.search}`;

  const init: RequestInit = {
    method: req.method,
    headers: forwardHeaders(req.headers, STRIP_REQUEST),
    body: ["GET", "HEAD"].includes(req.method) ? undefined : await req.text(),
  };

  const upstream = await fetch(url, init);

  const responseHeaders = forwardHeaders(upstream.headers, STRIP_RESPONSE);
  for (const cookie of upstream.headers.getSetCookie?.() ?? []) {
    responseHeaders.append("set-cookie", cookie);
  }

  return new Response(await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = (r: NextRequest, ctx: Ctx) => proxy(r, ctx);
export const POST = (r: NextRequest, ctx: Ctx) => proxy(r, ctx);
export const PUT = (r: NextRequest, ctx: Ctx) => proxy(r, ctx);
export const DELETE = (r: NextRequest, ctx: Ctx) => proxy(r, ctx);
export const PATCH = (r: NextRequest, ctx: Ctx) => proxy(r, ctx);
