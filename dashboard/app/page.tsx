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
  const topProjects = rankProjects(projects.filter((p) => p.segment === "defi"), defi.sortBy, networkGas).slice(0, 6);

  return (
    <main>
      {/* Hero — both charts plot REAL daily series from /metrics (null days break
          the line; a partial last day is dashed); the status pill is driven by
          /metrics/status instead of an unconditional LIVE label. */}
      <div className="container hero">
        <div>
          <h1>
            The data <span className="hl">truth layer</span> for Arc.
          </h1>
          <p>
            USDC gas paid, TVL, and the Arc Native Score — three views of the
            same dataset, read directly from Arc mainnet via RPC. No
            third-party indexer in the pipeline.
          </p>
          <div className="cta-row">
            <Link href="/projects" className="btn">
              Explore live data
            </Link>
            <Link href="#how-it-works" className="btn-ghost">
              How it works
            </Link>
          </div>
        </div>

        <div className="chart-panel">
          <div className="cap">
            <StatusPill status={status} />
          </div>
          <div className="mini-metrics">
            <div className="mini">
              <div className="mini-label">
                Arc gas paid <span>USDC per day, network-wide</span>
              </div>
              <Sparkline
                values={series((d) => d.usdc_gas_paid)}
                lastPartial={lastPartial}
                color="var(--accent)"
                ariaLabel="USDC gas paid per day on Arc"
              />
            </div>
            <div className="mini">
              <div className="mini-label">
                USDC movement <span>per day, network-wide</span>
              </div>
              <Sparkline
                values={series((d) => usdcByDay.get(d.day) ?? null)}
                lastPartial={lastPartial}
                color="var(--data-2)"
                ariaLabel="USDC movement per day on Arc"
              />
            </div>
            <div className="mini">
              <div className="mini-label">
                Active addresses <span>distinct senders per day</span>
              </div>
              <Sparkline
                values={series((d) => d.active_addresses)}
                lastPartial={lastPartial}
                color="#f2f0ea"
                ariaLabel="Active addresses per day on Arc"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Stat strip — every number here is real, per docs/BRANDING.md §5.
          No market cap: see supabase/migrations/20260924080000_network_stats.sql
          for why that's a separate, not-yet-built feature. */}
      <div className="container">
        <div className="stat-strip">
          <Stat big={String(stats?.total_projects ?? projects.length)} lbl="projects tracked" />
          <Stat big={formatUsdCompact(stats?.total_tvl_usd ?? null)} lbl="total value locked" />
          <Stat big={formatUsdCompact(stats?.total_volume_7d ?? null)} lbl="usdc/usyc moved (7d)" />
          <Stat big={formatCompact(stats?.total_tx_7d ?? null)} lbl="transactions (7d)" />
          <Stat big={formatCompact(stats?.total_unique_users_7d ?? null)} lbl="unique users (7d)" />
        </div>
        <p className="pt-note">
          Movement is gross (every transfer, including hops through contracts). Windows fill as
          days of data accrue — see <Link href="/network">Network</Link> for the daily detail.
        </p>
      </div>

      {/* Live preview — DeFi protocols ranked by TVL; other kinds of project are measured
          differently and live under /projects (see lib/segments.ts). */}
      <section className="section container">
        <div className="eyebrow">LIVE DATA</div>
        <h2>Top DeFi protocols, right now.</h2>
        <p className="lede">
          Ranked by value locked. Launchpads, infrastructure and tokens are measured with the
          metrics that fit them — browse each kind under Projects.
        </p>
        <SegmentTable projects={topProjects} config={defi} networkGas={networkGas} />
        <p className="pt-note">
          <Link href="/projects">Browse all {projects.length} tracked projects by type →</Link>
        </p>
      </section>

      {/* Pipeline — copy matches mockups/landing-page.html verbatim (this
          is our own product copy, not third-party content; the original
          wording is more precise than my earlier paraphrase, e.g. it
          correctly mentions checkpointing, which I'd dropped). */}
      <section className="section container tight" id="how-it-works">
        <div className="eyebrow">How the numbers are made</div>
        <h2>Three steps, one source of truth</h2>
        <p className="lede">
          Every figure on Isogram traces back through the same pipeline —
          nothing purchased from a third-party indexer, nothing estimated.
        </p>
        <div className="pipeline">
          <div className="pipe big">
            <div className="n">01</div>
            <h3>Ingest</h3>
            <p>
              Direct JSON-RPC reads against Arc mainnet, block by block,
              checkpointed so nothing is missed or duplicated.
            </p>
          </div>
          <div className="pipe">
            <div className="n">02</div>
            <h3>Normalize</h3>
            <p>
              Every USDC amount converted to its 6-decimal view at
              ingestion — gas and transfers on one consistent scale.
            </p>
          </div>
          <div className="pipe">
            <div className="n">03</div>
            <h3>Classify</h3>
            <p>
              Every contract is typed — DEX, lending, launchpad, infrastructure,
              token — and each type is measured with the metrics that fit it.
            </p>
          </div>
        </div>
      </section>

      {/* Trust */}
      <section className="section trust container">
        <div className="trust-inner">
          <p>
            <b>Isogram is research and ecosystem infrastructure, not a
            trading-signals product.</b> No paid data resale. No financial
            advice framing. Metric definitions are documented in full,
            never a black box — see the methodology in{" "}
            <Link href="https://github.com/only1angelnath/isogram">
              the public repo
            </Link>
            . Arc mainnet launched recently, so early numbers will be small
            — that&apos;s a fact about the chain&apos;s age, not something
            this page hides.
          </p>
        </div>
      </section>
    </main>
  );
}

function Stat({ big, lbl }: { big: string; lbl: string }) {
  return (
    <div className="stat" style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6, minWidth: 0 }}>
      <span className="big mono" style={{ fontSize: "clamp(1.25rem, 2.4vw, 1.9rem)", lineHeight: 1.1, whiteSpace: "nowrap" }}>{big}</span>
      <span className="lbl" style={{ margin: 0 }}>{lbl}</span>
    </div>
  );
}
