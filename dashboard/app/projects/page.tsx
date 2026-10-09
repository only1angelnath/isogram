import Link from "next/link";
import { getNetworkDaily, listProjects } from "@/lib/api";
import { SegmentTable } from "@/components/SegmentTable";
import { Pagination } from "@/components/Pagination";
import { ColumnKey, SEGMENTS, segmentConfig, sortProjects, sumGas } from "@/lib/segments";
import { paginate, parsePage, parseSort } from "@/lib/tableState";
import { formatCompact, formatUsdCompact } from "@/lib/format";
import { ProjectSummary, SegmentId } from "@/lib/types";

export const dynamic = "force-dynamic";

function overview(id: SegmentId, projects: ProjectSummary[]): { big: string; sub: string } {
  const tx = projects.reduce((s, p) => s + (p.tx_count_7d ?? 0), 0);
  const tvl = projects.reduce((s, p) => s + (p.tvl_usd ?? 0), 0);
  if (id === "defi") return { big: formatUsdCompact(tvl), sub: `locked · ${formatCompact(tx)} tx (7d)` };
  return { big: formatCompact(tx), sub: "transactions (7d)" };
}

export default async function ProjectsPage({ searchParams }: {
  searchParams: Promise<{ segment?: string; sort?: string; dir?: string; page?: string }>;
}) {
  const sp = await searchParams;
  const segment = sp.segment;
  const [all, days] = await Promise.all([listProjects(), getNetworkDaily(7)]);
  const networkGas = sumGas(days);

  const groups = SEGMENTS.map((cfg) => ({ cfg, items: all.filter((p) => (p.segment ?? "other") === cfg.id) })).filter((g) => g.items.length > 0);
  const selectedId = (groups.find((g) => g.cfg.id === segment)?.cfg.id ?? groups.find((g) => g.cfg.id === "defi")?.cfg.id ?? groups[0]?.cfg.id) as SegmentId | undefined;
  const cfg = segmentConfig(selectedId);
  const selected = groups.find((g) => g.cfg.id === selectedId)?.items ?? [];
  const sortState = parseSort(sp.sort, sp.dir, ["name", ...cfg.columns], { key: cfg.sortBy, dir: "desc" });
  const sorted = sortProjects(selected, sortState.key as ColumnKey | "name", sortState.dir, networkGas);
  const paged = paginate(sorted, parsePage(sp.page));
  const customSort = sortState.key !== cfg.sortBy || sortState.dir !== "desc";
  const pagerQuery = { segment: cfg.id, sort: customSort ? sortState.key : undefined, dir: customSort ? sortState.dir : undefined };

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
      <SegmentTable
        projects={paged.rows}
        config={cfg}
        networkGas={networkGas}
        startRank={paged.from || 1}
        sort={{ basePath: "/projects", query: { segment: cfg.id }, key: sortState.key, dir: sortState.dir }}
      />
      <Pagination paged={paged} basePath="/projects" query={pagerQuery} noun="projects" />
      <p className="pt-note">
        Click a column to sort; the full set is also in the public API (<code>GET /projects</code>).
        Names come from public on-chain metadata; <b>verified</b> marks hand-checked projects, everything else is discovered automatically and is not an endorsement.
      </p>
      {(cfg.id === "token" || cfg.id === "stablecoin") && (
        <p className="pt-note">
          Price, volume, FDV and liquidity are third-party data from GeckoTerminal, refreshed hourly. <b>24h vol</b> covers
          all pools; <b>7d vol</b> covers the token&apos;s most liquid pool only, so it can understate tokens that trade in
          several. <b>thin</b> means under
          $10,000 of liquidity and <b>no trading</b> means under 1% of liquidity traded in the last 24 hours; FDV is
          hidden in both cases. A <b>CoinGecko</b> tag means the token maps to a CoinGecko listing; without it the price
          comes from a DEX pool and is unverified. Not investment advice.
        </p>
      )}
    </main>
  );
}

