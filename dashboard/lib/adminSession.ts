// lib/adminSession.ts — server-only. The FastAPI admin key
// (ADMIN_API_KEY) never leaves this server: the browser only ever holds a
// signed session cookie, checked here, and app/api/admin-proxy attaches
// the real key when forwarding to the API. Two separate secrets on
// purpose: ADMIN_DASHBOARD_PASSWORD is what a human types once to log in
// (easy to share/rotate for a small team); ADMIN_API_KEY is what
// authenticates server-to-server to FastAPI and a human never sees it.

import { createHmac, timingSafeEqual } from "crypto";

const SESSION_COOKIE_NAME = "isogram_admin_session";
const SESSION_TTL_MS = 12 * 60 * 60 * 1000; // 12 hours

function getSigningSecret(): string {
  const secret = process.env.ADMIN_API_KEY;
  if (!secret) {
    throw new Error("ADMIN_API_KEY must be set (see dashboard/.env.example).");
  }
  return secret;
}

function sign(payload: string): string {
  return createHmac("sha256", getSigningSecret()).update(payload).digest("hex");
}

export function checkPassword(candidate: string): boolean {
  const expected = process.env.ADMIN_DASHBOARD_PASSWORD;
  if (!expected) {
    throw new Error(
      "ADMIN_DASHBOARD_PASSWORD must be set (see dashboard/.env.example)."
    );
  }
  const a = Buffer.from(candidate);
  const b = Buffer.from(expected);
  // Different-length buffers would throw in timingSafeEqual — pad the
  // comparison instead of short-circuiting on length, so a mismatched
  // length doesn't leak timing info either.
  if (a.length !== b.length) {
    timingSafeEqual(Buffer.alloc(32), Buffer.alloc(32)); // constant-time no-op
    return false;
  }
  return timingSafeEqual(a, b);
}

export function createSessionCookieValue(): string {
  const expiresAt = Date.now() + SESSION_TTL_MS;
  const payload = `${expiresAt}`;
  const signature = sign(payload);
  return `${payload}.${signature}`;
}

export function isValidSessionCookieValue(value: string | undefined): boolean {
  if (!value) return false;
  const [payload, signature] = value.split(".");
  if (!payload || !signature) return false;
  const expected = sign(payload);
  if (expected.length !== signature.length) return false;
  if (!timingSafeEqual(Buffer.from(expected), Buffer.from(signature))) return false;
  const expiresAt = Number(payload);
  return Number.isFinite(expiresAt) && Date.now() < expiresAt;
}

export { SESSION_COOKIE_NAME };
