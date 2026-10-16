// app/api/admin-login/route.ts — POST { password } -> sets a signed,
// httpOnly session cookie on success. This is the only place
// ADMIN_DASHBOARD_PASSWORD is checked; every subsequent admin action goes
// through app/api/admin-proxy, which trusts the cookie instead of asking
// for the password again.
//
// Failed attempts are limited (lib/loginLimit.ts: 5 per address per 15 minutes, 40 overall) and each
// failure waits briefly before answering, so guessing the password is slow even before the limit bites.

import { NextRequest, NextResponse } from "next/server";
import { checkPassword, createSessionCookieValue, SESSION_COOKIE_NAME } from "../../../lib/adminSession";
import { checkLoginAllowed, clientIp, recordLoginFailure, recordLoginSuccess } from "../../../lib/loginLimit";

const FAILURE_DELAY_MS = 400;

export async function POST(req: NextRequest) {
  const ip = clientIp(req);
  const gate = checkLoginAllowed(ip);
  if (!gate.allowed) {
    return NextResponse.json(
      { error: `Too many failed attempts. Try again in ${Math.max(1, Math.ceil(gate.retryAfterSec / 60))} min.` },
      { status: 429, headers: { "Retry-After": String(gate.retryAfterSec) } },
    );
  }

  let body: { password?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }

  if (!body.password || !checkPassword(body.password)) {
    recordLoginFailure(ip);
    await new Promise((resolve) => setTimeout(resolve, FAILURE_DELAY_MS));
    return NextResponse.json({ error: "Incorrect password" }, { status: 401 });
  }

  recordLoginSuccess(ip);
  const res = NextResponse.json({ status: "ok" });
  res.cookies.set(SESSION_COOKIE_NAME, createSessionCookieValue(), {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 12 * 60 * 60,
  });
  return res;
}
