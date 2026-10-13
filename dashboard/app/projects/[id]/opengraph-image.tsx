import { getProject } from "@/lib/api";
import { formatCount, formatScore, formatUsd, formatUsdCompact } from "@/lib/format";
import { OG_SIZE, renderProjectCard, renderSiteCard } from "@/lib/og";

export const alt = "Project on Isogram";
export const size = OG_SIZE;
export const contentType = "image/png";
export const dynamic = "force-dynamic";

// Per-project share card: name, category and whichever 7-day figures exist. Anything unknown is left
// out rather than shown as 0; if the API cannot answer, the generic site card is served instead.
export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const p = await getProject(id).catch(() => null);
  if (!p) return renderSiteCard();

  const stats: { label: string; value: string }[] = [];
  if (p.score !== null) stats.push({ label: "Score", value: formatScore(p.score) });
  if (p.tvl_usd !== null) stats.push({ label: "TVL", value: formatUsdCompact(p.tvl_usd) });
  if (p.tx_count_7d !== null) stats.push({ label: "Transactions 7d", value: formatCount(p.tx_count_7d) });
  if (p.usdc_gas_7d !== null && stats.length < 3) stats.push({ label: "USDC gas 7d", value: formatUsd(p.usdc_gas_7d) });
  return renderProjectCard({ name: p.name, category: p.category, stats: stats.slice(0, 3) });
}
