import Link from "next/link";
import type { Metadata } from "next";
import { getNetworkDaily, listProjects } from "@/lib/api";
import { SegmentTable } from "@/components/SegmentTable";
import { Pagination } from "@/components/Pagination";
import { CsvButton } from "@/components/CsvButton";
import { ColumnKey, SEGMENTS, segmentConfig, sortProjects, sumGas } from "@/lib/segments";
import { paginate, parsePage, parseSort } from "@/lib/tableState";
import { formatCompact, formatUsdCompact } from "@/lib/format";
import { ProjectSummary, SegmentId } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Projects" };

function overview(id: SegmentId, projects: ProjectSummary[]): string {
  const tx = projects.reduce((s, p) => s + (p.tx_count_7d ?? 0), 0);
  const tvl = projects.reduce((s, p) => s + (p.tvl_usd ?? 0), 0);
  return id === "defi" ? formatUsdCompact(tvl) + " locked" : formatCompact(tx) + " tx (7d)";
}

export default async function ProjectsPage({ searchParams }: {
  searchParams: Promise<{ segment?: string; sort?: string; dir?: string; page?: string }>;
}) {
  const sp = await searchParams;
  const segment = sp.segment;
  const [all, days] = await Promise.all([listProjects(), getNetworkDaily(7)]);
  const networkGas = sumGas(days);

  const groups = SEGMENTS.map((cfg) => ({ cfg, items: all.filter((p) => (p.segment ?? "other") === cfg.id) })).filter((g) => g.items.length > 0);
  const selectedId = (groups.find((g) => g.cfg.id === segment)?.cfg.id ?? groups.find((g) => g.cfg.id === "token")?.cfg.id ?? groups[0]?.cfg.id) as SegmentId | undefined;
  const cfg = segmentConfig(selectedId);
  const selected = groups.find((g) => g.cfg.id === selectedId)?.items ?? [];
  const sortState = parseSort(sp.sort, sp.dir, ["name", ...cfg.columns], { key: cfg.sortBy, dir: "desc" });
  const sorted = sortProjects(selected, sortState.key as ColumnKey | "name", sortState.dir, networkGas);
  const paged = paginate(sorted, parsePage(sp.page));
  const customSort = sortState.key !== cfg.sortBy || sortState.dir !== "desc";
  const pagerQuery = { segment: cfg.id, sort: customSort ? sortState.key : undefined, dir: customSort ? sortState.dir : undefined };
  const thirdParty = cfg.id === "token" || cfg.id === "stablecoin" || cfg.id === "launchpad";

  return (
    <main className="container section first">
      <div className="page-head">
        <div className="eyebrow">Projects</div>
        <h1>Everything tracked on Arc.</h1>
      </div>

      <div className="iso-cards compact">
        {groups.map(({ cfg: c, items }) => (
          <Link key={c.id} href={`/projects?segment=${c.id}`} className="iso-card" aria-current={c.id === selectedId ? "page" : undefined}>
            <div className="k">{c.label}</div>
            <div className="big">{items.length.toLocaleString("en-US")}</div>
            <div className="sub">{overview(c.id, items)}</div>
          </Link>
        ))}
      </div>

      <div className="section-head" style={{ marginBottom: 14 }}>
        <h2 style={{ fontSize: 22 }}>{cfg.label}</h2>
        <CsvButton
          label="All projects CSV"
          filename="isogram-projects.csv"
          columns={["id", "name", "segment", "category", "tier", "score", "tvl_usd", "usdc_gas_7d", "unique_users_7d", "tx_count_7d", "failed_tx_7d", "failed_rate_7d", "holders", "price_usd", "liquidity_usd", "volume_24h_usd", "market_quality", "scored_at"]}
          rows={all.map((p) => [p.id, p.name, p.segment, p.category, p.tier, p.score, p.tvl_usd, p.usdc_gas_7d, p.unique_users_7d, p.tx_count_7d, p.failed_tx_7d, p.failed_rate_7d, p.holders, p.market?.price_usd, p.market?.liquidity_usd, p.market?.volume_24h_usd, p.market?.quality, p.computed_at])}
        />
        <span className="iso-dim" style={{ fontSize: 14, flexBasis: "100%", margin: "-8px 0 0" }}>{cfg.blurb}</span>
      </div>

      <SegmentTable
        projects={paged.rows}
        config={cfg}
        networkGas={networkGas}
        startRank={paged.from || 1}
        sort={{ basePath: "/projects", query: { segment: cfg.id }, key: sortState.key, dir: sortState.dir }}
      />
      <Pagination paged={paged} basePath="/projects" query={pagerQuery} noun="projects" />
      <p className="pt-note">
        {thirdParty && <>Price, volume and liquidity are third-party data (GeckoTerminal). </>}
        Auto-discovered projects are not endorsed. <Link href="/docs/methodology#projects">How this works</Link>
      </p>
    </main>
  );
}
