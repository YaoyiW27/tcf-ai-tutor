/**
 * Server-side proxy to the FastAPI backend.
 *
 * The browser talks only to this origin; this route adds the backend's shared
 * secret and forwards. That is the whole reason it exists: anything the browser
 * holds is public, so `BACKEND_API_KEY` must never be a `NEXT_PUBLIC_` variable.
 * It also means the deployed backend needs no CORS entry for the frontend —
 * these calls are server-to-server.
 */

import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const BACKEND_API_KEY = process.env.BACKEND_API_KEY ?? "";

// Hop-by-hop and body-framing headers: forwarding them lets the upstream
// response describe a body fetch has already decoded.
const STRIP = new Set([
  "host",
  "connection",
  "content-length",
  "content-encoding",
  "transfer-encoding",
]);

function forwardHeaders(source: Headers): Headers {
  const headers = new Headers();
  source.forEach((value, key) => {
    if (!STRIP.has(key.toLowerCase())) headers.set(key, value);
  });
  if (BACKEND_API_KEY) headers.set("x-api-key", BACKEND_API_KEY);
  return headers;
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const url = `${BACKEND_URL}/${path.join("/")}${req.nextUrl.search}`;
  const hasBody = req.method !== "GET" && req.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers: forwardHeaders(req.headers),
      body: hasBody ? req.body : undefined,
      // Streaming a request body requires half duplex; audio uploads would
      // otherwise be buffered whole before the backend sees a byte.
      ...(hasBody ? { duplex: "half" } : {}),
      redirect: "manual",
    } as RequestInit);
  } catch (err) {
    // A backend that is down or misconfigured should read as a gateway failure,
    // not as an opaque 500 from the frontend.
    return Response.json(
      { detail: `Backend unreachable: ${(err as Error).message}` },
      { status: 502 },
    );
  }

  const headers = new Headers(upstream.headers);
  STRIP.forEach((h) => headers.delete(h));
  return new Response(upstream.body, { status: upstream.status, headers });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;

// Audio uploads and model responses are streamed rather than buffered, so this
// cannot be prerendered or cached.
export const dynamic = "force-dynamic";
