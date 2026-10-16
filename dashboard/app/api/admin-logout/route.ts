// app/api/admin-logout/route.ts — POST -> clears the admin session cookie. The cookie is httpOnly, so
// the browser cannot remove it itself; the server has to expire it.

import { NextResponse } from "next/server";
import { SESSION_COOKIE_NAME } from "../../../lib/adminSession";

export async function POST() {
  const res = NextResponse.json({ status: "ok" });
  res.cookies.set(SESSION_COOKIE_NAME, "", {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
  return res;
}
