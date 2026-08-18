import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Access gate for the deployed app.
 *
 * The backend's API key stops anyone calling it directly, but it does nothing
 * about the frontend: the proxy attaches that key to whatever arrives, so a
 * public URL is a public spend of Anthropic and OpenAI credits — one graded
 * essay is several model calls with extended thinking. This gate is what makes
 * the URL safe to publish.
 *
 * Unset APP_PASSWORD (the local default) leaves the app open, matching how the
 * backend treats API_KEY.
 */

const encoder = new TextEncoder();

/** SHA-256 both sides, then compare digests without an early exit.
 *
 * Middleware runs on the Edge runtime, which has Web Crypto but not Node's
 * timingSafeEqual. Hashing first makes the compared values fixed-length, so
 * neither the password's length nor its first differing character is leaked by
 * how long the comparison takes.
 */
async function matches(provided: string, expected: string): Promise<boolean> {
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  const x = new Uint8Array(a);
  const y = new Uint8Array(b);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

export async function middleware(req: NextRequest) {
  const password = process.env.APP_PASSWORD;
  if (!password) return NextResponse.next();

  const header = req.headers.get("authorization");
  if (header?.startsWith("Basic ")) {
    try {
      const decoded = atob(header.slice(6));
      // Any username; only the password is checked.
      const provided = decoded.slice(decoded.indexOf(":") + 1);
      if (await matches(provided, password)) return NextResponse.next();
    } catch {
      // Malformed header — fall through to the challenge.
    }
  }

  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="tcf-ai-tutor", charset="UTF-8"' },
  });
}

export const config = {
  // Everything except Next's static output. /api/backend is covered on purpose:
  // that route is the one that spends money.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
