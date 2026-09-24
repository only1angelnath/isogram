import Link from "next/link";
import { listProjects, getNetworkStats } from "@/lib/api";
import { ProjectTable } from "@/components/ProjectTable";
import { formatCount, formatUsd } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const [projects, stats] = await Promise.all([listProjects(), getNetworkStats()]);

  const topProjects = [...projects]
    .filter((p) => p.score !== null)
    .sort((a, b) => (b.score as number) - (a.score as number))
    .slice(0, 5);

  return (
    <main>
      {/* Hero — the chart panel is decorative motion only (no fabricated
          data points), per product decision; every number on this page
          comes from the API. */}
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
            <Link href="/gas" className="btn-ghost">
              Gas leaderboard
            </Link>
          </div>
        </div>

        <div className="chart-panel">
          <div className="cap">
            <span className="live">
              <span className="live-dot" /> ARC MAINNET · LIVE
            </span>
          </div>
          <div className="mini-metrics">
            <div className="mini">
              <div className="mini-label">
                USDC gas paid <span>· Arc mainnet</span>
              </div>
              <svg viewBox="0 0 160 50" width="100%" height="50">
                <path
                  className="chart-line"
                  d="M0 46 C 24 40, 40 16, 61 24 C 82 32, 104 11, 160 16"
                  fill="none"
                  stroke="var(--accent)"
                  strokeWidth="1.5"
                />
                <circle className="flow-dot a" r="2.5" />
              </svg>
            </div>
            <div className="mini">
              <div className="mini-label">
                Network volume <span>· Arc mainnet</span>
              </div>
              <svg viewBox="0 0 160 50" width="100%" height="50">
                <path
                  className="chart-line b"
                  d="M0 40 C 18 43, 30 48, 45 37 C 61 27, 72 13, 88 21 C 104 29, 114 45, 130 32 C 141 24, 149 11, 160 8"
                  fill="none"
                  stroke="var(--data-2)"
                  strokeWidth="1.5"
                />
                <circle className="flow-dot b" r="2.5" />
              </svg>
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
          <Stat big={formatUsd(stats?.total_tvl_usd ?? null)} lbl="total tvl" />
          <Stat big={formatUsd(stats?.total_volume_7d ?? null)} lbl="volume (7d)" />
          <Stat big={formatCount(stats?.total_tx_7d ?? null)} lbl="transactions (7d)" />
          <Stat big={formatCount(stats?.total_unique_users_7d ?? null)} lbl="unique users (7d)" />
        </div>
      </div>

      {/* Live preview — top scored projects, links to the full list */}
      <section className="section container">
        <div className="eyebrow">LIVE DATA</div>
        <h2>Top projects, right now.</h2>
        <p className="lede">
          Ranked by Arc Native Score — activity, USDC volume, TVL, and
          contract age, weighted equally and explained in full below.
        </p>
        <ProjectTable projects={topProjects} />
        <p className="pt-note">
          <Link href="/projects">View all {projects.length} tracked projects →</Link>
        </p>
      </section>

      {/* Pipeline */}
      <section className="section container tight">
        <div className="eyebrow">HOW IT WORKS</div>
        <h2>Ingest → Normalize → Score.</h2>
        <p className="lede">
          Every number on this page traces back to Arc mainnet through
          exactly three steps — no black box in between.
        </p>
        <div className="pipeline">
          <div className="pipe big">
            <div className="n">01</div>
            <h3>Ingest</h3>
            <p>
              A worker polls Arc mainnet directly over JSON-RPC
              (rpc.mainnet.arc.io) — no third-party indexer. It decodes every
              transaction&apos;s gas paid and every tracked token&apos;s
              Transfer events straight from the chain.
            </p>
          </div>
          <div className="pipe">
            <div className="n">02</div>
            <h3>Normalize</h3>
            <p>
              USDC is Arc&apos;s native gas asset, shown at two decimal
              resolutions. Every stored amount is converted to one
              consistent 6-decimal view before it ever reaches a database
              row.
            </p>
          </div>
          <div className="pipe">
            <div className="n">03</div>
            <h3>Score</h3>
            <p>
              Activity, volume, TVL, and contract age — normalized against
              every other tracked project and combined into one explainable
              number, recomputed on a schedule.
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
            advice framing. The scoring formula is documented in full,
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
    <div className="stat">
      <span className="big mono">{big}</span>
      <span className="lbl">{lbl}</span>
    </div>
  );
}
