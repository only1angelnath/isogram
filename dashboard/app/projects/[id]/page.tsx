import Link from "next/link";
import { notFound } from "next/navigation";
import { getNetworkDaily, getProject, getProjectDaily, getScoreHistory } from "@/lib/api";
import { InteractiveChart } from "@/components/InteractiveChart";
import { ScoreBadge } from "@/components/ScoreBadge";
import { ScoreGauge } from "@/components/ScoreGauge";
import { Avatar } from "@/components/Avatar";
import { fillCalendar } from "@/lib/series";
import { segmentConfig, sumGas } from "@/lib/segments";
import { failedTone, formatCount, formatPercent, formatPrice, formatRelativeAge, formatUsd, formatUsdCompact } from "@/lib/format";

interface ProjectPageProps {
  params: Promise<{ id: string }>;
}

export const dynamic = "force-dynamic";

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
    <main className="container section">
      <p className="mono" style={{ fontSize: 12, color: "var(--ink-dim)", marginBottom: 24 }}>
        <Link href={`/projects?segment=${cfg.id}`}>← {cfg.label.toLowerCase()}</Link>
      </p>

      <div style={{ display: "flex", alignItems: "center", gap: 24, marginBottom: 12, flexWrap: "wrap" }}>
        {cfg.showsScore && <ScoreGauge score={project.score} />}
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <Avatar name={project.name} />
          <div>
            <div style={{ marginBottom: 6 }}>
              <span className="iso-pill">{project.category ?? "unclassified"}</span>{" "}
              <span className="iso-pill">{cfg.short}</span>{" "}
              {project.tier === "curated" && <span className="iso-pill good">verified</span>}
            </div>
            <h1 style={{ fontSize: 32 }}>{project.name}</h1>
          </div>
        </div>
      </div>

      <p className="mono" style={{ fontSize: 12, color: "var(--ink-dim)", marginBottom: 28 }}>
        added {formatRelativeAge(project.created_at)} · last measured {formatRelativeAge(project.computed_at)}
      </p>

      {project.tier === "discovered" && (
        <p className="pt-note" style={{ marginBottom: 24 }}>
          Auto-discovered, not hand-verified. The name comes from public on-chain metadata and is not an
          endorsement or confirmation of who operates this contract.
        </p>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16, marginBottom: 32 }}>
        {stats.map((s) => (
          <div key={s.label} className="stat-panel">
            <div className="value mono">{s.tone !== undefined && s.tone !== "" ? <span className={`iso-pill ${s.tone}`} style={{ fontSize: 14 }}>{s.value}</span> : s.value}</div>
            <div className="label">{s.label}</div>
          </div>
        ))}
      </div>

      {!cfg.showsTvl && (
        <p className="pt-note" style={{ marginBottom: 24 }}>
          {cfg.label} are measured by usage, not value locked, so there is no TVL or score for this project.
        </p>
      )}

      {isPriced && (
        <div className="panel" style={{ padding: 20, marginBottom: 32 }}>
          <div style={{ fontWeight: 600, marginBottom: 12 }}>
            Market data <span className="iso-pill" style={{ marginLeft: 8 }}>third-party · GeckoTerminal</span>
          </div>
          {market ? (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 16, marginBottom: 12 }}>
                <div className="stat-panel"><div className="value mono">{formatPrice(market.price_usd)}</div><div className="label">price</div></div>
                <div className="stat-panel"><div className="value mono">{formatUsdCompact(market.fdv_usd)}</div><div className="label">fdv</div></div>
                <div className="stat-panel"><div className="value mono">{formatUsdCompact(market.liquidity_usd)}</div><div className="label">liquidity</div></div>
                <div className="stat-panel"><div className="value mono">{formatUsdCompact(market.volume_24h_usd)}</div><div className="label">volume (24h)</div></div>
                <div className="stat-panel" title="Last 7 UTC days in the token's most liquid pool only; can understate tokens that trade in several pools."><div className="value mono">{formatUsdCompact(market.volume_7d_usd ?? null)}</div><div className="label">volume (7d, top pool)</div></div>
              </div>
              {market.quality === "thin" && (
                <p className="pt-note" style={{ marginBottom: 8 }}>Liquidity is under $10,000, so this price is easy to move and FDV is not shown.</p>
              )}
              {market.quality === "inactive" && (
                <p className="pt-note" style={{ marginBottom: 8 }}>There is liquidity but almost no trading in the last 24 hours, so this price may be stale and FDV is not shown.</p>
              )}
              <p className="mono" style={{ fontSize: 12, color: "var(--ink-dim)" }}>
                updated {formatRelativeAge(market.fetched_at)} ·{" "}
                {market.listed_on_coingecko ? "mapped to a CoinGecko listing" : "not CoinGecko-listed: the price comes from a DEX pool and is unverified"}
              </p>
            </>
          ) : (
            <p className="no-data">
              No market data. GeckoTerminal does not index a trading pool for this token, or its last refresh is more than a day old.
            </p>
          )}
        </div>
      )}

      {cfg.showsScore && project.score === null && (
        <p className="no-data" style={{ marginBottom: 32 }}>
          This project hasn&apos;t been scored yet — either it was just added, or the chain is still too young
          for a meaningful reading. Check back after the next scoring run.
        </p>
      )}

      {daily.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 360px), 1fr))", gap: 16, marginBottom: 32 }}>
          <div className="panel" style={{ padding: 18 }}>
            <div style={{ fontWeight: 600, marginBottom: 12 }}>Transactions</div>
            <InteractiveChart kind="bar" points={txPts} format="count" yTitle="transactions per day" ariaLabel="Transactions per day" height={160} />
          </div>
          <div className="panel" style={{ padding: 18 }}>
            <div style={{ fontWeight: 600, marginBottom: 12 }}>USDC gas</div>
            <InteractiveChart kind="line" points={gasPts} format="usd4" color="var(--data-2)" yTitle="USDC gas per day" ariaLabel="USDC gas per day" height={160} />
          </div>
          <div className="panel" style={{ padding: 18 }}>
            <div style={{ fontWeight: 600, marginBottom: 12 }}>Unique users</div>
            <InteractiveChart kind="line" points={userPts} format="count" yTitle="distinct senders per day" ariaLabel="Unique users per day" height={160} />
          </div>
          {cfg.showsScore && scorePts.length > 1 && (
            <div className="panel" style={{ padding: 18 }}>
              <div style={{ fontWeight: 600, marginBottom: 12 }}>Arc Native Score</div>
              <InteractiveChart kind="line" points={scorePts} format="score" yTitle="score over time" ariaLabel="Arc Native Score over time" height={160} />
            </div>
          )}
        </div>
      )}

      {cfg.showsScore && (
        <div className="panel" style={{ padding: 24, marginBottom: 32 }}>
          <ScoreBadge projectId={project.id} projectName={project.name} />
        </div>
      )}

      <div>
        <p className="mono" style={{ fontSize: 12, color: "var(--ink-dim)", marginBottom: 8 }}>tracked contracts</p>
        <ul style={{ margin: 0, paddingLeft: 20 }}>
          {project.contracts.map((address) => (
            <li key={address} className="mono" style={{ fontSize: "0.85rem", marginBottom: 4 }}>
              <a href={`${EXPLORER}${address}`} target="_blank" rel="noreferrer">{address} ↗</a>
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}

