// segments.ts — what to measure for each kind of project (DeFiLlama-style).
//
// A single table of metrics for everything is wrong: TVL means something for a DEX or a
// lender and nothing for a router proxy or a memecoin; a launchpad is judged by activity;
// the composite Arc Native Score is only comparable inside a peer group of DeFi protocols.
// The API assigns each project a `segment` from its category (api/aggregate.py); this file
// decides, per segment, which columns to show and how to rank.

import { ProjectSummary, SegmentId } from "./types";

export type ColumnKey = "tvl" | "tx" | "users" | "gas" | "share" | "failed" | "score";

export interface SegmentConfig {
  id: SegmentId;
  label: string;
  short: string;
  blurb: string;
  columns: ColumnKey[];
  /** Primary ranking metric. */
  sortBy: ColumnKey;
  showsScore: boolean;
  showsTvl: boolean;
}

export const SEGMENTS: SegmentConfig[] = [
  {
    id: "defi",
    label: "DeFi protocols",
    short: "DeFi",
    blurb: "DEXs, lending, yield and staking. TVL applies here, and the Arc Native Score is computed only within this group.",
    columns: ["tvl", "tx", "users", "gas", "failed", "score"],
    sortBy: "tvl",
    showsScore: true,
    showsTvl: true,
  },
  {
    id: "launchpad",
    label: "Launchpads",
    short: "Launchpads",
    blurb: "Token factories and launch platforms. Judged by usage — transactions, users and the gas their activity burns — not TVL.",
    columns: ["tx", "users", "gas", "failed"],
    sortBy: "tx",
    showsScore: false,
    showsTvl: false,
  },
  {
    id: "infra",
    label: "Infrastructure",
    short: "Infra",
    blurb: "Routers, proxies, bridges, oracles and governance. Measured by how much they are used and how much network gas they account for.",
    columns: ["tx", "users", "gas", "share", "failed"],
    sortBy: "gas",
    showsScore: false,
    showsTvl: false,
  },
  {
    id: "token",
    label: "Tokens",
    short: "Tokens",
    blurb: "Tokens, memecoins and wrapped assets found on-chain. Price and market data are not tracked yet, so only on-chain usage is shown.",
    columns: ["tx", "users", "gas", "failed"],
    sortBy: "tx",
    showsScore: false,
    showsTvl: false,
  },
  {
    id: "stablecoin",
    label: "Stablecoins",
    short: "Stablecoins",
    blurb: "Hand-verified stablecoins (USDC, EURC, USYC). Their activity is shown here; supply tracking is not wired in yet.",
    columns: ["tx", "users", "gas", "failed"],
    sortBy: "tx",
    showsScore: false,
    showsTvl: false,
  },
  {
    id: "other",
    label: "Unclassified",
    short: "Other",
    blurb: "Contracts whose type has not been identified yet.",
    columns: ["tx", "users", "gas", "failed"],
    sortBy: "tx",
    showsScore: false,
    showsTvl: false,
  },
];

export function segmentConfig(id: SegmentId | null | undefined): SegmentConfig {
  return SEGMENTS.find((s) => s.id === id) ?? SEGMENTS[SEGMENTS.length - 1];
}

export const COLUMN_LABELS: Record<ColumnKey, string> = {
  tvl: "tvl",
  tx: "tx (7d)",
  users: "users (7d)",
  gas: "gas (7d)",
  share: "net. gas share",
  failed: "failed",
  score: "score",
};

/** The value a column shows for a project (null = not measured). */
export function metricOf(p: ProjectSummary, key: ColumnKey, networkGas: number | null): number | null {
  switch (key) {
    case "tvl": return p.tvl_usd;
    case "tx": return p.tx_count_7d;
    case "users": return p.unique_users_7d;
    case "gas": return p.usdc_gas_7d;
    case "failed": return p.failed_rate_7d;
    case "score": return p.score;
    case "share": return networkGas !== null && networkGas > 0 && p.usdc_gas_7d !== null ? p.usdc_gas_7d / networkGas : null;
  }
}

/** Descending by the segment's primary metric; unmeasured last; ties broken by activity. */
export function rankProjects(projects: ProjectSummary[], key: ColumnKey, networkGas: number | null): ProjectSummary[] {
  return [...projects].sort((a, b) => {
    const av = metricOf(a, key, networkGas);
    const bv = metricOf(b, key, networkGas);
    if (av === null && bv !== null) return 1;
    if (bv === null && av !== null) return -1;
    return (bv ?? 0) - (av ?? 0) || (b.tx_count_7d ?? 0) - (a.tx_count_7d ?? 0);
  });
}

export function sumGas(days: { usdc_gas_paid: number | null }[]): number | null {
  const vals = days.map((d) => d.usdc_gas_paid).filter((v): v is number => v !== null);
  return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
}
