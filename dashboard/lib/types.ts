// types.ts — mirrors api/models.py's ProjectSummary / ProjectDetail exactly.
// A project with no computed score yet has null numeric fields (never 0) —
// see docs/BUGS.md #3 — so every numeric field here is nullable, and every
// component that renders one must handle the null case explicitly rather
// than letting `0` slip through as if it were a real measurement.

export interface ProjectSummary {
  id: string;
  name: string;
  category: string | null;
  score: number | null;
  tvl_usd: number | null;
  usdc_gas_7d: number | null;
  unique_users_7d: number | null;
  computed_at: string | null;
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
  total_volume_7d: number | null;
  total_tx_7d: number | null;
  total_unique_users_7d: number | null;
  computed_at: string | null;
}
