// adminApi.ts - types and helpers shared by the admin panels. Every call goes through /api/admin-proxy
// (never FastAPI's /admin/* directly): the proxy checks the session cookie and attaches the admin key
// server-side, so the key never reaches the browser.

export const EXPLORER = "https://explorer.arc.io/address/";
export const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/;

export class SessionExpiredError extends Error {
  constructor() { super("SESSION_EXPIRED"); }
}

export async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/admin-proxy/${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (res.status === 401) throw new SessionExpiredError();
  // The API limits admin routes per address (so the admin key cannot be guessed). A person rarely hits it.
  if (res.status === 429) throw new Error("Too many admin requests in a minute. Wait a moment, then try again.");
  let body: unknown = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    const b = (body ?? {}) as { detail?: unknown; error?: string };
    const detail = typeof b.detail === "string" ? b.detail : Array.isArray(b.detail) ? "Check the fields and try again." : undefined;
    throw new Error(detail || b.error || `Request failed (${res.status})`);
  }
  return body as T;
}

export interface Submission {
  id: number;
  contract_address: string;
  proposed_name: string | null;
  proposed_category: string | null;
  socials: Record<string, string> | null;
  submitter_contact: string | null;
  note: string | null;
  status: "pending" | "approved" | "rejected";
  reviewed_at: string | null;
  reviewer_note: string | null;
  created_at: string;
}

export interface Discovered {
  contract_address: string;
  call_count: number;
  category: string | null;
  gecko_name: string | null;
  gecko_symbol: string | null;
  status: string;
  first_seen: string;
  last_seen: string;
}

export interface KeyRow {
  id: number;
  key_prefix: string;
  name: string;
  email: string | null;
  tier: string;
  rate_limit_per_minute: number | null;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface CategoryRow { category: string; segment: string }

export const SEGMENT_LABEL: Record<string, string> = {
  defi: "DeFi", token: "Tokens", stablecoin: "Stablecoins", launchpad: "Launchpads", infra: "Infrastructure", other: "Other",
};

// What each segment means for the project: this is what the reviewer is actually deciding.
export const SEGMENT_NOTE: Record<string, string> = {
  defi: "Tracked with TVL and an Arc Native Score, ranked against other DeFi protocols.",
  token: "Shown as a token: price, liquidity and holders (third-party data). Not scored.",
  stablecoin: "Shown as a stablecoin: price, liquidity and holders (third-party data). Not scored.",
  launchpad: "Shown as a launchpad: usage plus its own token's market data. Not scored.",
  infra: "Usage only (transactions, users, gas). No TVL and no score.",
};

export function segmentOf(category: string, categories: CategoryRow[]): string | null {
  return categories.find((c) => c.category === category)?.segment ?? null;
}

// The public form uses friendly labels; only some map cleanly onto the taxonomy. "DeFi protocol" is
// deliberately NOT mapped: the reviewer must choose between dex, lending, yield and liquid-staking.
const FORM_LABEL_TO_CATEGORY: Record<string, string> = {
  token: "token", stablecoin: "stablecoin", launchpad: "launchpad", infrastructure: "infra",
};

export function suggestCategory(proposed: string | null, categories: CategoryRow[]): string {
  const p = (proposed ?? "").trim().toLowerCase();
  if (categories.some((c) => c.category === p)) return p;
  return FORM_LABEL_TO_CATEGORY[p] ?? "";
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (!Number.isFinite(mins)) return "unknown";
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

export function shortAddress(a: string): string {
  return a.length > 14 ? `${a.slice(0, 8)}…${a.slice(-6)}` : a;
}

export function errorText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/** Only https links from a submitter are made clickable. */
export function safeHttpUrl(v: string | undefined | null): string | null {
  if (!v) return null;
  try {
    const u = new URL(v.trim());
    return u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}

/** "@acme" or "acme" -> a profile URL, only when it is a plain X handle. */
export function xUrl(v: string | undefined | null): string | null {
  const h = (v ?? "").trim().replace(/^@/, "");
  return /^[A-Za-z0-9_]{1,15}$/.test(h) ? `https://x.com/${h}` : null;
}

/**
 * A link to reply to a submitter: mailto: for an email address, t.me for an @handle or t.me link,
 * otherwise null (shown as plain text). Only plain, validated forms are linked.
 */
export function contactHref(contact: string | null, project: string | null): string | null {
  const c = (contact ?? "").trim();
  if (!c) return null;
  if (/^[^\s@<>"]+@[^\s@<>"]+\.[^\s@<>"]+$/.test(c)) {
    const subject = encodeURIComponent(`Your Isogram submission${project ? `: ${project}` : ""}`);
    return `mailto:${c}?subject=${subject}`;
  }
  const viaLink = /^(?:https?:\/\/)?t\.me\/([A-Za-z0-9_]{5,32})\/?$/i.exec(c);
  const handle = viaLink ? viaLink[1] : c.startsWith("@") ? c.slice(1) : "";
  return /^[A-Za-z0-9_]{5,32}$/.test(handle) ? `https://t.me/${handle}` : null;
}
