// segments.ts — what to measure for each kind of project (DeFiLlama-style).
//
// A single table of metrics for everything is wrong: TVL means something for a DEX or a
// lender and nothing for a router proxy or a memecoin; a launchpad is judged by activity;
// the composite Arc Native Score is only comparable inside a peer group of DeFi protocols.
// The API assigns each project a `segment` from its category (api/aggregate.py); this file
// decides, per segment, which columns to show and how to rank.

import { ProjectSummary, SegmentId } from "./types";

export type ColumnKey = "tvl" | "tx" | "users" | "gas" | "share" | "failed" | "score" | "price" | "fdv" | "liquidity" | "vol24h" | "vol7d" | "holders";

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
    blurb: "Launch platforms on Arc. Usage (transactions, users, gas) is measured on the platform's own contracts and token; the price, volume and liquidity columns describe the platform's own token and are third-party data from GeckoTerminal. Tokens launched through a platform appear under Tokens.",
    columns: ["price", "vol24h", "liquidity", "tx", "users", "gas"],
    sortBy: "vol24h",
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
    blurb: "Tokens, memecoins and wrapped assets found on-chain. Usage comes from the chain; price, volume, FDV and liquidity are third-party data from GeckoTerminal, shown only where a trading pool is indexed; the table is ranked by 24h trading volume. Token names are chosen by whoever deploys the contract: a token called \"Bitcoin\" is not necessarily Bitcoin.",
    columns: ["price", "vol24h", "vol7d", "liquidity", "fdv", "tx", "holders"],
    sortBy: "vol24h",
    showsScore: false,
    showsTvl: false,
  },
  {
    id: "stablecoin",
    label: "Stablecoins",
    short: "Stablecoins",
    blurb: "Hand-verified stablecoins (USDC, EURC, USYC). Usage comes from the chain; price and liquidity are third-party data from GeckoTerminal.",
    columns: ["price", "liquidity", "tx", "holders", "users", "failed"],
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
  users: "active users (7d)",
  gas: "gas (7d)",
  share: "net. gas share",
  failed: "failed",
  score: "score",
  price: "price",
  fdv: "fdv",
  liquidity: "liquidity",
  vol24h: "24h vol",
  vol7d: "7d vol",
  holders: "holders",
};

/** Hover text for columns whose basis is not obvious from the label. */
export const COLUMN_TITLES: Partial<Record<ColumnKey, string>> = {
  holders: "Addresses holding the token, from the Arc explorer (explorer.arc.io); refreshed about every 12 hours. Dash = not indexed as a token.",
  users: "Distinct addresses that interacted with the project's contracts in the last 7 days.",
  vol24h: "Trading volume in the last 24 hours across all pools (GeckoTerminal, third-party).",
  vol7d: "Trading volume over the last 7 UTC days, today included, in the token's most liquid pool only - it can understate tokens that trade in several pools (GeckoTerminal, third-party).",
  fdv: "Fully diluted valuation, shown only when the price is backed by real liquidity and trading.",
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
    case "price": return p.market?.price_usd ?? null;
    case "fdv": return p.market?.fdv_usd ?? null;
    case "liquidity": return p.market?.liquidity_usd ?? null;
    case "vol24h": return p.market?.volume_24h_usd ?? null;
    case "vol7d": return p.market?.volume_7d_usd ?? null;
    case "holders": return p.holders ?? null;
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

/**
 * Sort by any column (or the project name). Unmeasured values (null) always sort LAST, in
 * either direction, so "ascending by price" never opens with a wall of dashes. Ties fall
 * back to activity, then name, so the order is stable across page loads.
 */
export function sortProjects(
  projects: ProjectSummary[],
  key: ColumnKey | "name",
  dir: "asc" | "desc",
  networkGas: number | null,
): ProjectSummary[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...projects].sort((a, b) => {
    if (key === "name") {
      return sign * a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) || (b.tx_count_7d ?? 0) - (a.tx_count_7d ?? 0);
    }
    const av = metricOf(a, key, networkGas);
    const bv = metricOf(b, key, networkGas);
    if (av === null && bv !== null) return 1;
    if (bv === null && av !== null) return -1;
    return sign * ((av ?? 0) - (bv ?? 0)) || (b.tx_count_7d ?? 0) - (a.tx_count_7d ?? 0) || a.name.localeCompare(b.name);
  });
}

export function sumGas(days: { usdc_gas_paid: number | null }[]): number | null {
  const vals = days.map((d) => d.usdc_gas_paid).filter((v): v is number => v !== null);
  return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
}

