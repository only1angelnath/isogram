// api.ts — thin client of the Isogram FastAPI.
//
// Per docs/ARCHITECTURE.md §2.5, the dashboard is a client of the API, not a
// second copy of the query/DB logic — it never touches Postgres directly.
// These are plain async functions called from React Server Components
// (see docs/ARCHITECTURE.md: "server-rendered where practical"), so
// `fetch()` here runs on the server, not in the browser — API_BASE_URL
// never needs to be a NEXT_PUBLIC_ variable for that reason. The one place
// the API's URL reaches the browser is as a plain string inside a rendered
// <img src> for badge embeds (components/ScoreBadge.tsx) — no client-side
// fetch of it ever happens.

import {
  NetworkDay,
  NetworkStats,
  PipelineStatus,
  ProjectDay,
  ProjectDetail,
  ProjectSummary,
  ScorePoint,
  TokenDay,
  TopContract,
} from "./types";

function getApiBaseUrl(): string {
  const url = process.env.API_BASE_URL;
  if (!url) {
    throw new Error("API_BASE_URL must be set (see .env.example).");
  }
  return url.replace(/\/$/, "");
}

async function getJson<T>(path: string): Promise<T | null> {
  const res = await fetch(`${getApiBaseUrl()}${path}`, {
    // Deliberately not cached/ISR'd: this dashboard's build should never
    // depend on the API being reachable at BUILD time (a real risk on
    // Vercel if the API redeploys around the same time) — every page using
    // this client is marked `export const dynamic = "force-dynamic"` so
    // Next fetches fresh on each request instead of trying to prerender.
    cache: "no-store",
  });

  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Isogram API returned ${res.status} for ${path}`);
  }
  return res.json() as Promise<T>;
}

export async function listProjects(): Promise<ProjectSummary[]> {
  const data = await getJson<ProjectSummary[]>("/projects");
  return data ?? [];
}

export async function getProject(projectId: string): Promise<ProjectDetail | null> {
  return getJson<ProjectDetail>(`/projects/${encodeURIComponent(projectId)}`);
}

export async function getGasLeaderboard(limit = 25): Promise<ProjectSummary[]> {
  const data = await getJson<ProjectSummary[]>(`/gas/top?limit=${limit}`);
  return data ?? [];
}

export async function getNetworkStats(): Promise<NetworkStats | null> {
  return getJson<NetworkStats>("/stats");
}

// --- Metrics layer ---------------------------------------------------------------
// These ENRICH pages that already work without them, so a failure (API mid-deploy,
// a new endpoint not live yet) degrades to "no data" instead of taking the page down.

async function getOptional<T>(path: string): Promise<T | null> {
  try {
    return await getJson<T>(path);
  } catch {
    return null;
  }
}

export function getPipelineStatus(): Promise<PipelineStatus | null> {
  return getOptional<PipelineStatus>("/metrics/status");
}

export async function getNetworkDaily(days = 14): Promise<NetworkDay[]> {
  return (await getOptional<NetworkDay[]>(`/metrics/network/daily?days=${days}`)) ?? [];
}

export async function getTokensDaily(days = 14, token?: string): Promise<TokenDay[]> {
  const qs = `days=${days}${token ? `&token=${encodeURIComponent(token)}` : ""}`;
  return (await getOptional<TokenDay[]>(`/metrics/tokens/daily?${qs}`)) ?? [];
}

export async function getTopContracts(days = 7, limit = 15): Promise<TopContract[]> {
  return (await getOptional<TopContract[]>(`/metrics/contracts/top?days=${days}&limit=${limit}`)) ?? [];
}

export async function getProjectDaily(projectId: string, days = 14): Promise<ProjectDay[]> {
  return (await getOptional<ProjectDay[]>(`/projects/${encodeURIComponent(projectId)}/daily?days=${days}`)) ?? [];
}

export async function getScoreHistory(projectId: string, limit = 60): Promise<ScorePoint[]> {
  return (await getOptional<ScorePoint[]>(`/scores/${encodeURIComponent(projectId)}/history?limit=${limit}`)) ?? [];
}

export function getApiBaseUrlForBadge(): string {
  // Used only to build a plain string embedded in rendered HTML (an <img
  // src> or a copy-paste README snippet) — see the note above on why this
  // is safe without a NEXT_PUBLIC_ variable.
  return getApiBaseUrl();
}
