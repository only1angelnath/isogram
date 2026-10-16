// lib/loginLimit.ts - server-only. Best-effort limit on FAILED admin password attempts.
//
// Counters live in this server instance's memory (there is no shared store), so on a serverless host
// each warm instance counts separately and a restart clears them. That still turns unlimited guessing into
// a handful of tries per window per address, and the global cap bounds a distributed attempt. The real
// defence is a long random ADMIN_DASHBOARD_PASSWORD; this only slows guessing down.

const WINDOW_MS = 15 * 60 * 1000;
const MAX_FAILURES_PER_IP = 5;
const MAX_FAILURES_GLOBAL = 40;
const MAX_TRACKED_ADDRESSES = 2000;

interface Bucket { count: number; resetAt: number }

const perIp = new Map<string, Bucket>();
let global: Bucket = { count: 0, resetAt: 0 };

/** The caller's address as the host reports it. Vercel sets x-real-ip / x-forwarded-for itself. */
export function clientIp(req: Request): string {
  const real = req.headers.get("x-real-ip");
  if (real) return real.trim();
  const fwd = req.headers.get("x-forwarded-for");
  if (fwd) return fwd.split(",")[0].trim();
  return "unknown";
}

function live(b: Bucket | undefined, now: number): Bucket | null {
  return b && b.resetAt > now ? b : null;
}

export type LoginGate = { allowed: true } | { allowed: false; retryAfterSec: number };

export function checkLoginAllowed(ip: string, now: number = Date.now()): LoginGate {
  const g = live(global, now);
  if (g && g.count >= MAX_FAILURES_GLOBAL) return { allowed: false, retryAfterSec: Math.ceil((g.resetAt - now) / 1000) };
  const b = live(perIp.get(ip), now);
  if (b && b.count >= MAX_FAILURES_PER_IP) return { allowed: false, retryAfterSec: Math.ceil((b.resetAt - now) / 1000) };
  return { allowed: true };
}

export function recordLoginFailure(ip: string, now: number = Date.now()): void {
  const b = live(perIp.get(ip), now) ?? { count: 0, resetAt: now + WINDOW_MS };
  b.count += 1;
  perIp.set(ip, b);
  const g = live(global, now) ?? { count: 0, resetAt: now + WINDOW_MS };
  g.count += 1;
  global = g;
  if (perIp.size > MAX_TRACKED_ADDRESSES) {
    for (const [k, v] of perIp) if (v.resetAt <= now) perIp.delete(k);
    if (perIp.size > MAX_TRACKED_ADDRESSES) perIp.clear();
  }
}

export function recordLoginSuccess(ip: string): void {
  perIp.delete(ip);
}

/** Test helper: forget everything. */
export function resetLoginLimits(): void {
  perIp.clear();
  global = { count: 0, resetAt: 0 };
}
