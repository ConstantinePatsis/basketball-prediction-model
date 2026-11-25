import { NextResponse } from "next/server";

// Private site: HTTP basic auth. Set SITE_PASSWORD (and optionally SITE_USER) in Vercel's environment variables.
export function proxy(req) {
  const password = process.env.SITE_PASSWORD;
  if (!password) return new NextResponse("Site locked: set SITE_PASSWORD in Vercel.", { status: 503 });
  const user = process.env.SITE_USER || "konstantinos";
  const auth = req.headers.get("authorization") || "";
  if (auth.startsWith("Basic ")) {
    const [u, p] = atob(auth.slice(6)).split(":");
    if (u === user && p === password) return NextResponse.next();
  }
  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="EuroLeague model", charset="UTF-8"' },
  });
}
export const config = { matcher: "/((?!_next/static|_next/image|favicon.ico).*)" };
