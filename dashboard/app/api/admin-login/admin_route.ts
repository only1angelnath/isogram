// app/api/admin-proxy/[...path]/route.ts — every admin UI action goes
// through here. Checks the session cookie set by admin-login, then
// forwards to FastAPI's /admin/<path> with X-Admin-Key attached from
// server env. The real admin key is never sent to or readable by the
// browser at any point in this flow.

import { NextRequest, NextResponse } from "next/server";
import { isValidSessionCookieValue, SESSION_COOKIE_NAME } from "../../../../lib/adminSession";

function getApiBaseUrl(): string {
  const url = process.env.API_BASE_URL;
  if (!url) {
    throw new Error("API_BASE_URL must be set (see .env.example).");
  }
  return url.replace(/\/$/, "");
}

async function handle(req: NextRequest, params: { path: string[] }): Promise<NextResponse> {
  const session = req.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (!isValidSessionCookieValue(session)) {
    return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  }

  const adminKey = process.env.ADMIN_API_KEY;
  if (!adminKey) {
    return NextResponse.json({ error: "Admin proxy not configured" }, { status: 503 });
  }

  const targetPath = params.path.join("/");
  const search = req.nextUrl.search;
  const targetUrl = `${getApiBaseUrl()}/admin/${targetPath}${search}`;

  const init: RequestInit = {
    method: req.method,
    headers: { "Content-Type": "application/json", "X-Admin-Key": adminKey },
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  const upstream = await fetch(targetUrl, init);
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
  });
}

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, context: RouteContext) {
  return handle(req, await context.params);
}
export async function POST(req: NextRequest, context: RouteContext) {
  return handle(req, await context.params);
}
