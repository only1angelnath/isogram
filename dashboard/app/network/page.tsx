import { getNetworkDaily, getPipelineStatus, getTokensDaily, getTopContracts } from "@/lib/api";
import { InteractiveChart } from "@/components/InteractiveChart";
import { DailyTable } from "@/components/DailyTable";
import { TopContractsTable } from "@/components/TopContractsTable";
import { StatusPill } from "@/components/StatusPill";
import { fillCalendar } from "@/lib/series";
import { formatCompact, formatCount, formatDay, formatDuration, formatPercent, formatUsd } from "@/lib/format";

export const dynamic = "force-dynamic";

const USDC = "0x3600000000000000000000000000000000000000";

export default async function NetworkPage() {
  const [status, days, tokens, top] = await Promise.all([
    getPipelineStatus(),
    getNetworkDaily(30),
    getTokensDaily(30),
    getTopContracts(7, 15),
  ]);

  const usdcByDay = new Map(tokens.filter((t) => t.token_address === USDC).map((t) => [t.day, t.volume]));
  const last = days[days.length - 1];
  const topShare = top.reduce((s, c) => s + (c.gas_share ?? 0), 0);
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
    <main className="container section">
      <div className="eyebrow">NETWORK</div>
      <h2 style={{ fontSize: 32, marginBottom: 12 }}>What is happening on Arc.</h2>
      <p className="lede">
        Chain-wide activity read directly from Arc mainnet receipts: transactions, failures,
        USDC gas, deployments, active addresses and USDC movement. Days are UTC. Hover any chart
        for exact values.
      </p>

      <p className="mono" style={{ fontSize: 12, marginBottom: 20 }}>
        <StatusPill status={status} />
        {status?.data_through && (
          <span style={{ color: "var(--ink-dim)" }}> · data through {status.data_through.slice(0, 16).replace("T", " ")} UTC</span>
        )}
      </p>

      {status?.status === "behind" && (
        <p className="no-data" style={{ marginBottom: 24 }}>
          Ingestion is {formatDuration(status.lag_seconds)} behind the chain tip, so the newest days are
          incomplete (hatched). Older days are final.
        </p>
      )}

      {days.length === 0 ? (
        <p className="no-data">No network data yet — check back after the next ingestion run.</p>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 380px), 1fr))", gap: 16, marginBottom: 36 }}>
            <ChartCard title="Transactions" value={formatCount(last?.tx_count ?? null)} day={last}>
              <InteractiveChart kind="bar" points={txPts} format="count" yTitle="transactions per day" ariaLabel="Transactions per day" />
            </ChartCard>
            <ChartCard title="Failed transaction rate" value={formatPercent(last?.failed_rate ?? null)} day={last}>
              <InteractiveChart kind="bar" points={failedPts} format="percent" color="#e3b45c" yTitle="% of transactions that failed" ariaLabel="Failed transaction rate per day" />
            </ChartCard>
            <ChartCard title="USDC gas paid" value={formatUsd(last?.usdc_gas_paid ?? null)} day={last}>
              <InteractiveChart kind="line" points={gasPts} format="usd" color="var(--data-2)" yTitle="USDC gas per day" ariaLabel="USDC gas paid per day" />
            </ChartCard>
            <ChartCard title="Active addresses" value={formatCount(last?.active_addresses ?? null)} day={last}>
              <InteractiveChart kind="line" points={addrPts} format="count" yTitle="distinct senders per day" ariaLabel="Active addresses per day" />
            </ChartCard>
            <ChartCard title="Contracts deployed" value={formatCount(last?.contract_creations ?? null)} day={last}>
              <InteractiveChart kind="bar" points={deployPts} format="count" color="var(--data-2)" yTitle="deployments per day" ariaLabel="Contract deployments per day" />
            </ChartCard>
            <ChartCard title="USDC movement" value={formatCompact(usdcByDay.get(last?.day ?? "") ?? null)} day={last}>
              <InteractiveChart kind="bar" points={movePts} format="usdCompact" yTitle="USDC moved per day" ariaLabel="USDC movement per day" />
            </ChartCard>
          </div>

          <div className="eyebrow" style={{ marginBottom: 12 }}>DAILY BREAKDOWN</div>
          <div style={{ marginBottom: 40 }}>
            <DailyTable days={days.slice(-14)} usdcByDay={usdcByDay} />
          </div>
        </>
      )}

      <div className="eyebrow" style={{ marginBottom: 8 }}>TOP CONTRACTS BY GAS · LAST 7 DAYS</div>
      {top.length === 0 ? (
        <p className="no-data" style={{ marginBottom: 32 }}>No contract activity recorded yet.</p>
      ) : (
        <>
          <p className="lede" style={{ marginBottom: 14 }}>
            The 15 busiest contracts paid {formatPercent(topShare, 0)} of all network gas;{" "}
            <b>{formatPercent(unattributed, 0)}</b> came from contracts Isogram has not classified yet
            (<i>untracked</i> means unclassified — not unverified or malicious). Gas is paid by the
            people calling a contract, so it measures how heavily a contract is used.
          </p>
          <div style={{ marginBottom: 36 }}>
            <TopContractsTable contracts={top} />
          </div>
        </>
      )}

      <div className="panel" style={{ padding: 24 }}>
        <div className="eyebrow" style={{ marginBottom: 8 }}>HOW TO READ THESE NUMBERS</div>
        <ul style={{ margin: 0, paddingLeft: 20, fontSize: 14, lineHeight: 1.7 }}>
          <li><b>USDC gas</b> is gas actually paid (gas used × effective gas price), in the 6-decimal USDC view. Failed transactions still pay gas.</li>
          <li><b>USDC movement</b> is gross: every explicit USDC transfer — native sends and ERC-20 transfers, counted once — including intermediate hops through contracts such as routers. It is not economic volume. Mints and burns are excluded.</li>
          <li><b>Active addresses</b> are distinct transaction senders that day.</li>
          <li><b>Hatched bars / dashed lines</b> are partial days (still accruing or not fully ingested). <b>Dotted gaps</b> are days Isogram did not cover — nothing is filled in. <b>Early data</b> days predate failure, deployment and block tracking, so those values are blank rather than zero.</li>
        </ul>
      </div>
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
    <div className="panel" style={{ padding: "18px 18px 14px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14, gap: 12 }}>
        <span style={{ fontWeight: 600, fontSize: 15 }}>{title}</span>
        <span style={{ textAlign: "right" }}>
          <span className="mono" style={{ fontSize: 18 }}>{value}</span>
          {day && (
            <span className="mono" style={{ display: "block", fontSize: 10, color: "var(--ink-dim)" }}>
              {formatDay(day.day)}{day.partial ? " · partial" : ""}
            </span>
          )}
        </span>
      </div>
      {children}
    </div>
  );
}
