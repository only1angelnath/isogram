// projectsCsv.ts - the "all projects" CSV: one definition of the columns, used by the route that serves it.
// Built on the server on request, so the project list is never shipped to the browser as page data.

import { CsvCell } from "@/lib/csv";
import { ProjectSummary } from "@/lib/types";

export const PROJECT_CSV_FILENAME = "isogram-projects.csv";

export const PROJECT_CSV_COLUMNS = [
  "id", "name", "segment", "category", "tier", "score", "tvl_usd", "usdc_gas_7d", "unique_users_7d",
  "tx_count_7d", "failed_tx_7d", "failed_rate_7d", "holders", "price_usd", "liquidity_usd",
  "volume_24h_usd", "market_quality", "scored_at",
];

export function projectCsvRow(p: ProjectSummary): CsvCell[] {
  return [
    p.id, p.name, p.segment, p.category, p.tier, p.score, p.tvl_usd, p.usdc_gas_7d, p.unique_users_7d,
    p.tx_count_7d, p.failed_tx_7d, p.failed_rate_7d, p.holders, p.market?.price_usd, p.market?.liquidity_usd,
    p.market?.volume_24h_usd, p.market?.quality, p.computed_at,
  ];
}
