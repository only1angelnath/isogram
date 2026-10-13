import Link from "next/link";
import { getNetworkDaily, getNetworkStats, getPipelineStatus, getTokensDaily, listProjects } from "@/lib/api";
import { SegmentTable } from "@/components/SegmentTable";
import { Sparkline } from "@/components/Sparkline";
import { StatusPill } from "@/components/StatusPill";
import { formatCompact, formatDay, formatUsd, formatUsdCompact } from "@/lib/format";
import { fillCalendar } from "@/lib/series";
import { rankProjects, segmentConfig, sumGas } from "@/lib/segments";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const [projects, stats, days, usdcDays, status] = await Promise.all([
    listProjects(),
    getNetworkStats(),
    getNetworkDaily(8),
    getTokensDaily(8, "USDC"),
    getPipelineStatus(),
  ]);
  const usdcByDay = new Map(usdcDays.map((t) => [t.day, t.volume]));
  const lastPartial = days.length > 0 && days[days.length - 1].partial;
  const series = (pick: (d: (typeof days)[number]) => number | null) =>
    fillCalendar(days, (d) => ({ value: pick(d), partial: d.partial })).map((p) => p.value);
  const networkGas = sumGas(days);

  // Headline value for each hero row = the latest COMPLETED day (never the partial day), with a
  // change vs the day before only when that day is the adjacent calendar day and also complete.
  const headline = (pick: (d: (typeof days)[number]) => number | null) => {
    const pts = fillCalendar(days, (d) => ({ value: pick(d), partial: d.partial }));
    let i = pts.length - 1;
    while (i >= 0 && (pts[i].partial || pts[i].value === null)) i--;
    if (i < 0) return null;
    const cur = pts[i];
    const prev = i > 0 && !pts[i - 1].partial ? pts[i - 1].value : null;
    const change = prev !== null && prev !== 0 && cur.value !== null ? (cur.value - prev) / prev : null;
    return { value: cur.value as number, day: cur.label, prevDay: i > 0 ? pts[i - 1].label : null, change };
  };
  const span = fillCalendar(days, (d) => ({ value: d.active_addresses }));
  const rangeLabel = span.length > 1 ? `${formatDay(span[0].label)} – ${formatDay(span[span.length - 1].label)}` : null;
  const usdcMoved = (d: (typeof days)[number]) => usdcByDay.get(d.day) ?? null;
  const gasHead = headline((d) => d.usdc_gas_paid);
  const moveHead = headline(usdcMoved);
  const addrHead = headline((d) => d.active_addresses);

  const defi = segmentConfig("defi");
  const tokens = segmentConfig("token");
  const topDefi = rankProjects(projects.filter((p) => p.segment === "defi"), defi.sortBy, networkGas).slice(0, 5);
  const topTokens = rankProjects(projects.filter((p) => p.segment === "token" && p.market), tokens.sortBy, networkGas).slice(0, 5);

  return (
    <main>
      <div className="container hero">
        <div className="hero-copy">
          <div>
            <h1>
              The data <span className="hl">truth layer</span> for Arc.
            </h1>
            <p>Live network activity, projects, tokens and DEX volume for Arc mainnet, with every figure sourced and labelled.</p>
          </div>
          <div className="hero-cta">
            <Link href="/projects" className="btn">Explore projects</Link>
            <Link href="/docs/api" className="btn-ghost">API docs</Link>
          </div>
        </div>

        <div className="chart-panel">
          <div className="cap">
            <StatusPill status={status} />
            {rangeLabel && <span className="cap-range" title="UTC calendar days. The dashed end of each line is today so far.">{rangeLabel} · UTC</span>}
          </div>
          <div className="mini-metrics">
            <HeroRow label="Gas paid" unit="USDC / day" head={gasHead} fmt={fmtGas}
              values={series((d) => d.usdc_gas_paid)} lastPartial={lastPartial} color="var(--accent)" aria="USDC gas paid per day on Arc" />
            <HeroRow label="USDC movement" unit="per day" head={moveHead} fmt={formatUsdCompact}
              values={series(usdcMoved)} lastPartial={lastPartial} color="var(--data-2)" aria="USDC movement per day on Arc" />
            <HeroRow label="Active addresses" unit="per day" head={addrHead} fmt={formatCompact}
              values={series((d) => d.active_addresses)} lastPartial={lastPartial} color="#f2f0ea" aria="Active addresses per day on Arc" />
          </div>
        </div>
      </div>

      <div className="container">
        <div className="stat-strip">
          <Stat big={String(stats?.total_projects ?? projects.length)} lbl="projects tracked" />
          <Stat big={formatUsdCompact(stats?.total_tvl_usd ?? null)} lbl="DeFi TVL" />
          <Stat big={formatUsdCompact(stats?.total_volume_7d ?? null)} lbl="USDC & USYC moved (7d)" />
          <Stat big={formatCompact(stats?.total_tx_7d ?? null)} lbl="transactions (7d)" />
          <Stat big={formatCompact(stats?.total_unique_users_7d ?? null)} lbl="active users (7d)" />
        </div>
      </div>

      <section className="section first container">
        <div className="section-head">
          <h2>Top tokens</h2>
          <Link href="/projects?segment=token" className="link-more">All tokens →</Link>
        </div>
        <SegmentTable projects={topTokens} config={tokens} networkGas={networkGas} />
      </section>

      <section className="section container" style={{ paddingTop: 0 }}>
        <div className="section-head">
          <h2>Top DeFi protocols</h2>
          <Link href="/projects?segment=defi" className="link-more">All DeFi →</Link>
        </div>
        <SegmentTable projects={topDefi} config={defi} networkGas={networkGas} />
      </section>
    </main>
  );
}

function Stat({ big, lbl }: { big: string; lbl: string }) {
  return (
    <div className="stat">
      <span className="big">{big}</span>
      <span className="lbl">{lbl}</span>
    </div>
  );
}

function fmtGas(v: number | null): string {
  if (v === null) return "—";
  if (v >= 1000) return formatUsdCompact(v);
  return formatUsd(v, { decimals: v < 1 ? 4 : 2 });
}

interface Head { value: number; day: string; prevDay: string | null; change: number | null }

function HeroRow({ label, unit, head, fmt, values, lastPartial, color, aria }: {
  label: string; unit: string; head: Head | null; fmt: (v: number | null) => string;
  values: (number | null)[]; lastPartial: boolean; color: string; aria: string;
}) {
  const ch = head?.change ?? null;
  return (
    <div className="mini">
      <div className="mini-text">
        <div className="mini-label">{label} <span>{unit}</span></div>
        <div className="mini-value">{head ? fmt(head.value) : "—"}</div>
        <div className="mini-sub">
          <span>{head ? `${formatDay(head.day)} (full day)` : "no completed day yet"}</span>
          {ch !== null && head?.prevDay && (
            <b className={ch >= 0 ? "up" : "down"}>{ch >= 0 ? "+" : "−"}{Math.abs(ch * 100).toFixed(1)}% vs {formatDay(head.prevDay)}</b>
          )}
        </div>
      </div>
      <div className="mini-chart">
        <Sparkline values={values} lastPartial={lastPartial} color={color} height={56} ariaLabel={aria} />
      </div>
    </div>
  );
}
