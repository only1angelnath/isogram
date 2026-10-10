// types.ts — mirrors api/models.py's ProjectSummary / ProjectDetail exactly.
// A project with no computed score yet has null numeric fields (never 0) —
// see docs/BUGS.md #3 — so every numeric field here is nullable, and every
// component that renders one must handle the null case explicitly rather
// than letting `0` slip through as if it were a real measurement.

export type SegmentId = "defi" | "launchpad" | "infra" | "token" | "stablecoin" | "other";

/** Third-party market data (GeckoTerminal), token and stablecoin projects only. Not chain-derived. */
export interface MarketData {
  price_usd: number | null;
  /** Withheld (null) unless quality is "ok": FDV inherits every flaw of the price. */
  fdv_usd: number | null;
  market_cap_usd: number | null;
  liquidity_usd: number | null;
  volume_24h_usd: number | null;
  /** Last 7 UTC days in the token's most liquid pool only (can understate); null = unknown/stale. */
  volume_7d_usd?: number | null;
  /** ok = trustworthy; thin = under $10k liquidity; inactive = reserves but ~no trading. */
  quality: "ok" | "thin" | "inactive";
  listed_on_coingecko: boolean;
  source: string;
  fetched_at: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  category: string | null;
  /** Decides which metrics apply: TVL/score mean something for DeFi, not for a token. */
  segment: SegmentId | null;
  /** "curated" = hand-seeded ecosystem project; "discovered" = auto-promoted by discovery. */
  tier: "curated" | "discovered" | null;
  score: number | null;
  tvl_usd: number | null;
  usdc_gas_7d: number | null;
  unique_users_7d: number | null;
  tx_count_7d: number | null;
  failed_tx_7d: number | null;
  failed_rate_7d: number | null;
  computed_at: string | null;
  /** null/absent = no usable market data (no pool indexed, no price, or older than 24h). */
  market?: MarketData | null;
  /** Addresses holding the token (Arc explorer); token / stablecoin / launchpad projects. null = unknown. */
  holders?: number | null;
}

export interface ProjectDetail extends ProjectSummary {
  contracts: string[];
  created_at: string | null;
}

// Mirrors api/models.py's NetworkStats — the dashboard's stat-strip data.
// Deliberately no market cap (see supabase/migrations/20260924080000_network_stats.sql).
export interface NetworkStats {
  total_projects: number;
  total_scored: number;
  total_tvl_usd: number | null;
  avg_score: number | null;
  total_volume_7d: number | null;
  total_tx_7d: number | null;
  total_unique_users_7d: number | null;
  computed_at: string | null;
}


// --- Metrics layer (api/routes/metrics.py, 2026-10-05) ---------------------------
// Every numeric field is nullable: null means "not measured" (e.g. failed_tx_count on
// a raw_backfill day, or a rate with no transactions), never 0.

/** GET /metrics/status — freshness of the data. Read before trusting "latest" values. */
export interface PipelineStatus {
  status: "live" | "behind" | "unknown";
  last_block_number: number | null;
  /** Timestamp of the last block ingestion has applied. */
  data_through: string | null;
  lag_seconds: number | null;
  checkpoint_updated_at: string | null;
}

/** GET /metrics/network/daily */
export interface NetworkDay {
  day: string; // YYYY-MM-DD (UTC)
  tx_count: number | null;
  failed_tx_count: number | null;
  failed_rate: number | null;
  usdc_gas_paid: number | null;
  avg_gas_per_tx_usdc: number | null;
  contract_creations: number | null;
  blocks: number | null;
  token_transfer_count: number | null;
  active_addresses: number | null;
  source: "live" | "raw_backfill" | null;
  /** True when the day is not fully covered yet (still accruing, or ingestion hasn't finished it). */
  partial: boolean;
}

/** GET /metrics/tokens/daily — volume is in the token's own 6-decimal units. */
export interface TokenDay {
  day: string;
  token_address: string;
  symbol: string | null;
  transfer_count: number | null;
  volume: number | null;
  avg_transfer_size: number | null;
}

/** GET /metrics/contracts/top */
export interface TopContract {
  contract_address: string;
  project_id: string | null;
  project_name: string | null;
  category: string | null;
  tx_count: number | null;
  failed_tx_count: number | null;
  failed_rate: number | null;
  usdc_gas: number | null;
  gas_share: number | null;
}

/** GET /projects/{id}/daily */
export interface ProjectDay {
  day: string;
  tx_count: number | null;
  failed_tx_count: number | null;
  failed_rate: number | null;
  usdc_gas: number | null;
  unique_users: number | null;
}

/** GET /scores/{id}/history (newest first) */
export interface ScorePoint {
  computed_at: string;
  score: number | null;
  tvl_usd: number | null;
  usdc_gas_7d: number | null;
  unique_users_7d: number | null;
}

