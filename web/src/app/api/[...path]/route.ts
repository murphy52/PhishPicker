import type { NextRequest } from "next/server";

const API_BASE = process.env.API_INTERNAL_URL ?? "http://api:8000";

async function proxyRequest(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const url = `${API_BASE}/${path.join("/")}${req.nextUrl.search}`;

  const init: RequestInit = { method: req.method };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  const upstream = await fetch(url, init);
  const data = await upstream.json();
  return Response.json(data, { status: upstream.status });
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const DELETE = proxyRequest;
