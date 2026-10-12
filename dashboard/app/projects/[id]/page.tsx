import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getNetworkDaily, getProject, getProjectDaily, getScoreHistory } from "@/lib/api";
import { InteractiveChart } from "@/components/InteractiveChart";
import { ScoreBadge } from "@/components/ScoreBadge";
import { ScoreGauge } from "@/components/ScoreGauge";
import { Avatar } from "@/components/Avatar";
import { fillCalendar } from "@/lib/series";
import { segmentConfig, sumGas } from "@/lib/segments";
import { SocialLinks } from "@/components/SocialLinks";
import { failedTone, formatChange, formatCount, formatPercent, formatPrice, formatRelativeAge, formatUsd, formatUsdCompact } from "@/lib/format";

interface ProjectPageProps {
  params: Promise<{ id: string }>;
}

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: ProjectPageProps): Promise<Metadata> {
  const { id } = await params;
  const project = await getProject(id).catch(() => null);
  return { title: project ? project.name : "Project" };
}

const EXPLORER = "https://explorer.arc.io/address/";

function scoreLabel(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })} ${String(d.getUTCHours()).padStart(2, "0")}:00`;
}

export default async function ProjectDetailPage({ params }: ProjectPageProps) {
  const { id } = await params;
  const project = await getProject(id);
  if (!project) {
    notFound();
  }

  const cfg = segmentConfig(project.segment);
  const [daily, history, netDays] = await Promise.all([
    getProjectDaily(id, 30),
    cfg.showsScore ? getScoreHistory(id, 60) : Promise.resolve([]),
    getNetworkDaily(7),
  ]);
  const networkGas = sumGas(netDays);
  const market = project.market ?? null;
  const isPriced = project.segment === "token" || project.segment === "stablecoin" || project.segment === "launchpad";
  const share = networkGas && project.usdc_gas_7d !== null ? project.usdc_gas_7d / networkGas : null;

  const txPts = fillCalendar(daily, (d) => ({ value: d.tx_count, detail: d.failed_tx_count ? [`${formatCount(d.failed_tx_count)} failed`] : undefined }));
  const gasPts = fillCalendar(daily, (d) => ({ value: d.usdc_gas }));
  const userPts = fillCalendar(daily, (d) => ({ value: d.unique_users }));
  const scorePts = [...history].reverse().map((h) => ({ label: scoreLabel(h.computed_at), value: h.score }));

  // Stat panels follow the project's segment: TVL only where value is locked.
  const stats: { label: string; value: string; tone?: string }[] = [];
  if (cfg.showsTvl) stats.push({ label: "tvl", value: formatUsd(project.tvl_usd) });
  stats.push({ label: "transactions (7d)", value: formatCount(project.tx_count_7d) });
  if (project.segment !== "token") stats.push({ label: "active users (7d)", value: formatCount(project.unique_users_7d) });
  if (isPriced && project.holders != null) stats.push({ label: "holders", value: formatCount(project.holders) });
  stats.push({ label: "usdc gas (7d)", value: formatUsd(project.usdc_gas_7d, { decimals: 4 }) });
  if (!cfg.showsTvl) stats.push({ label: "share of network gas", value: formatPercent(share, 2) });
  stats.push({ label: "failed tx rate (7d)", value: formatPercent(project.failed_rate_7d), tone: failedTone(project.failed_rate_7d) });

  return (
    <main className="container section first">
      <p className="crumb">
        <Link href={`/projects?segment=${cfg.id}`}>← {cfg.label}</Link>
      </p>

      <div className="detail-head">
        {cfg.showsScore && <ScoreGauge score={project.score} />}
        <Avatar name={project.name} />
        <div style={{ minWidth: 0 }}>
          <div style={{ marginBottom: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
            <span className="iso-pill">{project.category ?? "unclassified"}</span>
            {project.tier === "curated" ? (
              <span className="iso-pill good">verified</span>
            ) : (
              <span className="iso-pill dashed" title="Found automatically. The name comes from public on-chain metadata and is not an endorsement.">auto-discovered</span>
            )}
          </div>
          <h1>{project.name}</h1>
        </div>
      </div>

      <p className="meta">added {formatRelativeAge(project.created_at)} · measured {formatRelativeAge(project.computed_at)}</p>
      {(project.socials ?? []).length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <SocialLinks links={project.socials} />
        </div>
      )}

      <div className="stat-grid">
        {stats.map((s) => (
          <div key={s.label} className="stat-panel">
            <div className="value mono">{s.tone !== undefined && s.tone !== "" ? <span className={`iso-pill ${s.tone}`} style={{ fontSize: 14 }}>{s.value}</span> : s.value}</div>
            <div className="label">{s.label}</div>
          </div>
        ))}
      </div>

      {isPriced && (
        <div className="panel" style={{ padding: 18, marginBottom: 28 }}>
          <div style={{ fontWeight: 600, marginBottom: 12, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            Market <span className="iso-pill" title="Price data comes from GeckoTerminal, not from the chain.">third-party</span>
            {market?.quality === "thin" && <span className="iso-pill warn" title="Under $10,000 of liquidity: the price is easy to move, so FDV is not shown.">thin liquidity</span>}
            {market?.quality === "inactive" && <span className="iso-pill warn" title="Liquidity exists but almost nothing traded in 24h: the price may be stale, so FDV is not shown.">no trading</span>}
          </div>
          {market ? (
            <>
              <div className="stat-grid" style={{ marginBottom: 12 }}>
                <div className="stat-panel"><div className="value mono">{formatPrice(market.price_usd)}</div><div className="label">price{market.price_change_24h_pct != null && <span style={{ color: market.price_change_24h_pct > 0 ? "#5FC9C0" : market.price_change_24h_pct < 0 ? "#FF5B2E" : undefined }}> · {formatChange(market.price_change_24h_pct)} 24h</span>}</div></div>
                <div className="stat-panel"><div className="value mono">{formatUsdCompact(market.fdv_usd)}</div><div className="label">fdv</div></div>
                <div className="stat-panel"><div className="value mono">{formatUsdCompact(market.liquidity_usd)}</div><div className="label">liquidity</div></div>
                <div className="stat-panel"><div className="value mono">{formatUsdCompact(market.volume_24h_usd)}</div><div className="label">volume (24h)</div></div>
                <div className="stat-panel" title="Last 7 UTC days in the token's most liquid pool only; can understate tokens that trade in several pools."><div className="value mono">{formatUsdCompact(market.volume_7d_usd ?? null)}</div><div className="label">volume (7d, top pool)</div></div>
              </div>
              <p className="meta" style={{ margin: 0 }}>
                updated {formatRelativeAge(market.fetched_at)} · {market.listed_on_coingecko ? "CoinGecko-listed" : "DEX price, not verified"}
              </p>
            </>
          ) : (
            <p className="no-data" style={{ margin: 0 }}>No market data: no trading pool is indexed for this token, or the last refresh is over a day old.</p>
          )}
        </div>
      )}

      {cfg.showsScore && project.score === null && (
        <p className="notice">Not scored yet. Scores refresh every four hours.</p>
      )}

      {daily.length > 0 && (
        <div className="grid-charts" style={{ marginBottom: 28 }}>
          <div className="panel chart-card">
            <div className="hd"><b>Transactions</b></div>
            <InteractiveChart kind="bar" points={txPts} format="count" ariaLabel="Transactions per day" height={160} />
          </div>
          <div className="panel chart-card">
            <div className="hd"><b>USDC gas</b></div>
            <InteractiveChart kind="line" points={gasPts} format="usd4" color="var(--data-2)" ariaLabel="USDC gas per day" height={160} />
          </div>
          <div className="panel chart-card">
            <div className="hd"><b>Unique users</b></div>
            <InteractiveChart kind="line" points={userPts} format="count" ariaLabel="Unique users per day" height={160} />
          </div>
          {cfg.showsScore && scorePts.length > 1 && (
            <div className="panel chart-card">
              <div className="hd"><b>Arc Native Score</b></div>
              <InteractiveChart kind="line" points={scorePts} format="score" ariaLabel="Arc Native Score over time" height={160} />
            </div>
          )}
        </div>
      )}

      {cfg.showsScore && (
        <div className="panel" style={{ padding: 20, marginBottom: 28 }}>
          <ScoreBadge projectId={project.id} projectName={project.name} />
        </div>
      )}

      <div>
        <p className="meta" style={{ marginBottom: 8 }}>contracts</p>
        <ul className="contracts">
          {project.contracts.map((address) => (
            <li key={address}>
              <a href={`${EXPLORER}${address}`} target="_blank" rel="noreferrer">{address} ↗</a>
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}
