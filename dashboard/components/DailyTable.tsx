import { NetworkDay } from "@/lib/types";
import { failedTone, formatCompact, formatCount, formatDay, formatPercent, formatUsd } from "@/lib/format";

// Data-bar cell: a bar behind the number, scaled to the column maximum.
function barStyle(value: number | null, max: number, color: string): React.CSSProperties {
  const w = value !== null && max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return { ["--w" as string]: `${w}%`, ["--bar" as string]: color };
}

export function DailyTable({ days, usdcByDay }: { days: NetworkDay[]; usdcByDay: Map<string, number | null> }) {
  const rows = [...days].reverse();
  const maxTx = Math.max(0, ...days.map((d) => d.tx_count ?? 0));
  const maxGas = Math.max(0, ...days.map((d) => d.usdc_gas_paid ?? 0));
  const maxUsdc = Math.max(0, ...days.map((d) => usdcByDay.get(d.day) ?? 0));

  return (
    <div className="iso-table-wrap">
      <table className="iso-table">
        <thead>
          <tr>
            <th>day</th><th>transactions</th><th>failed</th><th>gas (usdc)</th><th>gas / tx</th>
            <th>deployed</th><th>active addr</th><th>usdc moved</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d, i) => {
            const moved = usdcByDay.get(d.day) ?? null;
            return (
              <tr key={d.day} style={{ animationDelay: `${i * 40}ms`, opacity: d.partial ? 0.8 : 1 }}>
                <td>
                  <span style={{ fontWeight: 600 }}>{formatDay(d.day)}</span>{" "}
                  {d.partial && <span className="iso-pill dashed">partial</span>}
                  {d.source === "raw_backfill" && <span className="iso-pill dashed" title="Predates failure, deployment and block tracking">early data</span>}
                </td>
                <td className="iso-num iso-bartd" style={barStyle(d.tx_count, maxTx, "rgba(255,91,46,.2)")}>{formatCount(d.tx_count)}</td>
                <td><span className={`iso-pill ${failedTone(d.failed_rate)}`}>{formatPercent(d.failed_rate)}</span></td>
                <td className="iso-num iso-bartd" style={barStyle(d.usdc_gas_paid, maxGas, "rgba(95,201,192,.2)")}>{formatUsd(d.usdc_gas_paid)}</td>
                <td className="iso-num iso-dim">{formatUsd(d.avg_gas_per_tx_usdc, { decimals: 4 })}</td>
                <td className="iso-num">{formatCount(d.contract_creations)}</td>
                <td className="iso-num">{formatCount(d.active_addresses)}</td>
                <td className="iso-num iso-bartd" style={barStyle(moved, maxUsdc, "rgba(255,91,46,.2)")}>{formatCompact(moved)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
