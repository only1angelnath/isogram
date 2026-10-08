import Link from "next/link";
import { TopContract } from "@/lib/types";
import { Avatar } from "@/components/Avatar";
import { failedTone, formatCount, formatPercent, formatUsd, shortAddress } from "@/lib/format";

const EXPLORER = "https://explorer.arc.io/address/";

function barStyle(value: number | null, max: number, color: string): React.CSSProperties {
  const w = value !== null && max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return { ["--w" as string]: `${w}%`, ["--bar" as string]: color };
}

export function TopContractsTable({ contracts }: { contracts: TopContract[] }) {
  const maxTx = Math.max(0, ...contracts.map((c) => c.tx_count ?? 0));
  const maxGas = Math.max(0, ...contracts.map((c) => c.usdc_gas ?? 0));
  const maxShare = Math.max(0, ...contracts.map((c) => c.gas_share ?? 0));

  return (
    <div className="iso-table-wrap">
      <table className="iso-table">
        <thead>
          <tr><th>contract</th><th>type</th><th>transactions</th><th>failed</th><th>gas (usdc)</th><th>share of network gas</th></tr>
        </thead>
        <tbody>
          {contracts.map((c, i) => (
            <tr key={c.contract_address} style={{ animationDelay: `${i * 40}ms` }}>
              <td>
                <div className="iso-cell-main">
                  <span className="iso-rank">{i + 1}</span>
                  <Avatar name={c.project_name ?? c.contract_address.slice(2)} />
                  <div style={{ minWidth: 0 }}>
                    {c.project_id ? (
                      <Link href={`/projects/${c.project_id}`} style={{ fontWeight: 600 }}>{c.project_name}</Link>
                    ) : (
                      <span className="iso-dim" style={{ fontWeight: 600 }}>Unclassified contract</span>
                    )}
                    <div>
                      <a className="iso-num iso-dim" style={{ fontSize: 11 }} href={`${EXPLORER}${c.contract_address}`} target="_blank" rel="noreferrer">
                        {shortAddress(c.contract_address)} ↗
                      </a>
                    </div>
                  </div>
                </div>
              </td>
              <td>
                {c.project_id ? <span className="iso-pill">{c.category ?? "project"}</span> : <span className="iso-pill dashed">untracked</span>}
              </td>
              <td className="iso-num iso-bartd" style={barStyle(c.tx_count, maxTx, "rgba(255,91,46,.2)")}>{formatCount(c.tx_count)}</td>
              <td><span className={`iso-pill ${failedTone(c.failed_rate)}`}>{formatPercent(c.failed_rate)}</span></td>
              <td className="iso-num iso-bartd" style={barStyle(c.usdc_gas, maxGas, "rgba(95,201,192,.2)")}>{formatUsd(c.usdc_gas)}</td>
              <td className="iso-num iso-bartd" style={barStyle(c.gas_share, maxShare, "rgba(255,91,46,.2)")}>{formatPercent(c.gas_share)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
