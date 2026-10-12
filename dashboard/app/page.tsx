import Link from "next/link";
import { getNetworkDaily, getNetworkStats, getPipelineStatus, getTokensDaily, listProjects } from "@/lib/api";
import { SegmentTable } from "@/components/SegmentTable";
import { Sparkline } from "@/components/Sparkline";
import { StatusPill } from "@/components/StatusPill";
import { formatCompact, formatUsdCompact } from "@/lib/format";
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

  const defi = segmentConfig("defi");
  const tokens = segmentConfig("token");
  const topDefi = rankProjects(projects.filter((p) => p.segment === "defi"), defi.sortBy, networkGas).slice(0, 5);
  const topTokens = rankProjects(projects.filter((p) => p.segment === "token" && p.market), tokens.sortBy, networkGas).slice(0, 5);

  return (
    <main>
      <div className="container hero">
        <div>
          <h1>
            The data <span className="hl">truth layer</span> for Arc.
          </h1>
          <p>Live network activity, projects, tokens and DEX volume for Arc mainnet, with every figure sourced and labelled.</p>
          <Link href="/projects" className="btn">Explore projects</Link>
        </div>

        <div className="chart-panel">
          <div className="cap">
            <StatusPill status={status} />
          </div>
          <div className="mini-metrics">
            <div className="mini">
              <div className="mini-label">Gas paid <span>USDC / day</span></div>
              <Sparkline values={series((d) => d.usdc_gas_paid)} lastPartial={lastPartial} color="var(--accent)" ariaLabel="USDC gas paid per day on Arc" />
            </div>
            <div className="mini">
              <div className="mini-label">USDC movement <span>per day</span></div>
              <Sparkline values={series((d) => usdcByDay.get(d.day) ?? null)} lastPartial={lastPartial} color="var(--data-2)" ariaLabel="USDC movement per day on Arc" />
            </div>
            <div className="mini">
              <div className="mini-label">Active addresses <span>per day</span></div>
              <Sparkline values={series((d) => d.active_addresses)} lastPartial={lastPartial} color="#f2f0ea" ariaLabel="Active addresses per day on Arc" />
            </div>
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
