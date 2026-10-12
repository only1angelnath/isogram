import Link from "next/link";
import type { Metadata } from "next";
import { getNetworkDaily, getPipelineStatus, getTokensDaily, getTopContracts } from "@/lib/api";
import { InteractiveChart } from "@/components/InteractiveChart";
import { DailyTable } from "@/components/DailyTable";
import { TopContractsTable } from "@/components/TopContractsTable";
import { StatusPill } from "@/components/StatusPill";
import { fillCalendar } from "@/lib/series";
import { firstParam } from "@/lib/tableState";
import { formatCompact, formatCount, formatDay, formatDuration, formatPercent, formatUsd } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Network" };

const USDC = "0x3600000000000000000000000000000000000000";
const RANGES = [7, 30, 90] as const;

export default async function NetworkPage({ searchParams }: { searchParams: Promise<{ range?: string }> }) {
  const sp = await searchParams;
  const asked = Number.parseInt(firstParam(sp.range) ?? "", 10);
  const range = (RANGES as readonly number[]).includes(asked) ? asked : 30;

  const [status, days, tokens, top] = await Promise.all([
    getPipelineStatus(),
    getNetworkDaily(range),
    getTokensDaily(range),
    getTopContracts(7, 15),
  ]);

  const usdcByDay = new Map(tokens.filter((t) => t.token_address === USDC).map((t) => [t.day, t.volume]));
  const last = days[days.length - 1];
  const unattributed = top.filter((c) => c.project_id === null).reduce((s, c) => s + (c.gas_share ?? 0), 0);

  const txPts = fillCalendar(days, (d) => ({ value: d.tx_count, partial: d.partial }));
  const failedPts = fillCalendar(days, (d) => ({
    value: d.failed_rate,
    partial: d.partial,
    detail: d.failed_tx_count !== null && d.tx_count !== null
      ? [`${formatCount(d.failed_tx_count)} of ${formatCount(d.tx_count)} transactions failed`]
      : ["Failures were not tracked on this day"],
  }));
  const gasPts = fillCalendar(days, (d) => ({
    value: d.usdc_gas_paid,
    partial: d.partial,
    detail: d.avg_gas_per_tx_usdc !== null ? [`${formatUsd(d.avg_gas_per_tx_usdc, { decimals: 4 })} per transaction`] : undefined,
  }));
  const addrPts = fillCalendar(days, (d) => ({ value: d.active_addresses, partial: d.partial }));
  const deployPts = fillCalendar(days, (d) => ({ value: d.contract_creations, partial: d.partial }));
  const movePts = fillCalendar(days, (d) => ({ value: usdcByDay.get(d.day) ?? null, partial: d.partial }));

  return (
    <main className="container section first">
      <div className="page-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="eyebrow">Network</div>
          <h1>What is happening on Arc.</h1>
        </div>
        <div className="range" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <Link key={r} href={r === 30 ? "/network" : `/network?range=${r}`} aria-current={r === range ? "page" : undefined}>{r}d</Link>
          ))}
        </div>
      </div>

      <p className="mono" style={{ fontSize: 12, margin: "0 0 20px" }}>
        <StatusPill status={status} />
        {status?.data_through && (
          <span className="iso-dim"> · data through {status.data_through.slice(0, 16).replace("T", " ")} UTC</span>
        )}
      </p>

      {status?.status === "behind" && (
        <p className="notice">Ingestion is {formatDuration(status.lag_seconds)} behind the chain tip, so the newest days are incomplete (hatched). Older days are final.</p>
      )}

      {days.length === 0 ? (
        <p className="no-data">No network data yet. Check back after the next ingestion run.</p>
      ) : (
        <>
          <div className="grid-charts" style={{ marginBottom: 40 }}>
            <ChartCard title="Transactions" value={formatCount(last?.tx_count ?? null)} day={last}>
              <InteractiveChart kind="bar" points={txPts} format="count" ariaLabel="Transactions per day" />
            </ChartCard>
            <ChartCard title="Failed transaction rate" value={formatPercent(last?.failed_rate ?? null)} day={last}>
              <InteractiveChart kind="bar" points={failedPts} format="percent" color="#e3b45c" ariaLabel="Failed transaction rate per day" />
            </ChartCard>
            <ChartCard title="USDC gas paid" value={formatUsd(last?.usdc_gas_paid ?? null)} day={last}>
              <InteractiveChart kind="line" points={gasPts} format="usd" color="var(--data-2)" ariaLabel="USDC gas paid per day" />
            </ChartCard>
            <ChartCard title="Active addresses" value={formatCount(last?.active_addresses ?? null)} day={last}>
              <InteractiveChart kind="line" points={addrPts} format="count" ariaLabel="Active addresses per day" />
            </ChartCard>
            <ChartCard title="Contracts deployed" value={formatCount(last?.contract_creations ?? null)} day={last}>
              <InteractiveChart kind="bar" points={deployPts} format="count" color="var(--data-2)" ariaLabel="Contract deployments per day" />
            </ChartCard>
            <ChartCard title="USDC movement" value={formatCompact(usdcByDay.get(last?.day ?? "") ?? null)} day={last}>
              <InteractiveChart kind="bar" points={movePts} format="usdCompact" ariaLabel="USDC movement per day" />
            </ChartCard>
          </div>

          <div className="section-head"><h2 style={{ fontSize: 22 }}>Daily breakdown</h2></div>
          <div style={{ marginBottom: 40 }}>
            <DailyTable days={days.slice(-14)} usdcByDay={usdcByDay} />
          </div>
        </>
      )}

      <div className="section-head">
        <h2 style={{ fontSize: 22 }}>Top contracts by gas · 7 days</h2>
      </div>
      {top.length === 0 ? (
        <p className="no-data">No contract activity recorded yet.</p>
      ) : (
        <>
          <TopContractsTable contracts={top} />
          {unattributed > 0 && (
            <p className="pt-note">{formatPercent(unattributed, 0)} of network gas comes from contracts not classified yet.</p>
          )}
        </>
      )}

      <p className="pt-note" style={{ marginTop: 28 }}>
        Hatched bars are partial days; dotted gaps are days not covered. Definitions: <Link href="/methodology#network">methodology</Link>.
      </p>
    </main>
  );
}

function ChartCard({ title, value, day, children }: {
  title: string;
  value: string;
  day: { day: string; partial: boolean } | undefined;
  children: React.ReactNode;
}) {
  return (
    <div className="panel chart-card">
      <div className="hd">
        <b>{title}</b>
        <span>
          <span className="v">{value}</span>
          {day && <span className="d">{formatDay(day.day)}{day.partial ? " · partial" : ""}</span>}
        </span>
      </div>
      {children}
    </div>
  );
}
