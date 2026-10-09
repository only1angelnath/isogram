import Link from "next/link";
import { getNetworkDaily, listProjects } from "@/lib/api";
import { SegmentTable } from "@/components/SegmentTable";
import { SEGMENTS, rankProjects, segmentConfig, sumGas } from "@/lib/segments";
import { formatCompact, formatUsdCompact } from "@/lib/format";
import { ProjectSummary, SegmentId } from "@/lib/types";

export const dynamic = "force-dynamic";

const ROW_LIMIT = 100;

function overview(id: SegmentId, projects: ProjectSummary[]): { big: string; sub: string } {
  const tx = projects.reduce((s, p) => s + (p.tx_count_7d ?? 0), 0);
  const tvl = projects.reduce((s, p) => s + (p.tvl_usd ?? 0), 0);
  if (id === "defi") return { big: formatUsdCompact(tvl), sub: `locked · ${formatCompact(tx)} tx (7d)` };
  return { big: formatCompact(tx), sub: "transactions (7d)" };
}

export default async function ProjectsPage({ searchParams }: { searchParams: Promise<{ segment?: string }> }) {
  const { segment } = await searchParams;
  const [all, days] = await Promise.all([listProjects(), getNetworkDaily(7)]);
  const networkGas = sumGas(days);

  const groups = SEGMENTS.map((cfg) => ({ cfg, items: all.filter((p) => (p.segment ?? "other") === cfg.id) })).filter((g) => g.items.length > 0);
  const selectedId = (groups.find((g) => g.cfg.id === segment)?.cfg.id ?? groups.find((g) => g.cfg.id === "defi")?.cfg.id ?? groups[0]?.cfg.id) as SegmentId | undefined;
  const cfg = segmentConfig(selectedId);
  const selected = groups.find((g) => g.cfg.id === selectedId)?.items ?? [];
  const ranked = rankProjects(selected, cfg.sortBy, networkGas);
  const shown = ranked.slice(0, ROW_LIMIT);

  return (
    <main className="container section">
      <div className="eyebrow">PROJECTS</div>
      <h2 style={{ fontSize: 32, marginBottom: 12 }}>Everything tracked on Arc, by type.</h2>
      <p className="lede">
        A DEX, a launchpad, a router and a memecoin are not the same kind of thing, so each type is
        measured with the metrics that fit it — TVL only where value is locked, the Arc Native
        Score only among DeFi protocols.
      </p>

      <div className="iso-cards" style={{ marginTop: 28 }}>
        {groups.map(({ cfg: c, items }, i) => {
          const o = overview(c.id, items);
          return (
            <Link key={c.id} href={`/projects?segment=${c.id}`} className="iso-card" aria-current={c.id === selectedId ? "page" : undefined} style={{ animationDelay: `${i * 60}ms` }}>
              <div className="k">{c.label}</div>
              <div className="big">{o.big}</div>
              <div className="sub">{items.length} tracked · {o.sub}</div>
            </Link>
          );
        })}
      </div>

      <div className="eyebrow" style={{ marginBottom: 8 }}>{cfg.label.toUpperCase()} · {selected.length}</div>
      <p className="lede" style={{ marginBottom: 16 }}>{cfg.blurb}</p>
      <SegmentTable projects={shown} config={cfg} networkGas={networkGas} />
      <p className="pt-note">
        {ranked.length > shown.length && <>Showing the top {shown.length} of {ranked.length}, ranked by {cfg.sortBy === "tvl" ? "value locked" : cfg.sortBy === "gas" ? "gas paid" : "transactions"}. The full set is in the public API (<code>GET /projects</code>). </>}
        Names come from public on-chain metadata; <b>verified</b> marks hand-checked projects, everything else is discovered automatically and is not an endorsement.
      </p>
      {(cfg.id === "token" || cfg.id === "stablecoin") && (
        <p className="pt-note">
          Price, FDV and liquidity are third-party data from GeckoTerminal, refreshed hourly. <b>thin</b> means under
          $10,000 of liquidity and <b>no trading</b> means under 1% of liquidity traded in the last 24 hours; FDV is
          hidden in both cases. A <b>CoinGecko</b> tag means the token maps to a CoinGecko listing; without it the price
          comes from a DEX pool and is unverified. Not investment advice.
        </p>
      )}
    </main>
  );
}

