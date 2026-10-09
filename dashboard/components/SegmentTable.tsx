import Link from "next/link";
import { ProjectSummary } from "@/lib/types";
import { Avatar } from "@/components/Avatar";
import { COLUMN_LABELS, ColumnKey, SegmentConfig, metricOf } from "@/lib/segments";
import { failedTone, formatCount, formatPercent, formatPrice, formatScore, formatUsd, formatUsdCompact } from "@/lib/format";

function cell(key: ColumnKey, p: ProjectSummary, networkGas: number | null): string {
  const v = metricOf(p, key, networkGas);
  switch (key) {
    case "tvl": return v === null ? "—" : formatUsdCompact(v);
    case "tx":
    case "users": return formatCount(v);
    case "gas": return formatUsd(v, { decimals: v !== null && v < 10 ? 4 : 2 });
    case "share": return formatPercent(v);
    case "failed": return formatPercent(v);
    case "score": return formatScore(v);
    case "price": return formatPrice(v);
    case "fdv":
    case "liquidity": return v === null ? "—" : formatUsdCompact(v);
  }
}

const QUALITY_NOTE: Record<string, { label: string; title: string }> = {
  thin: { label: "thin", title: "Under $10,000 of liquidity: this price is easy to move, so FDV is not shown." },
  inactive: { label: "no trading", title: "Liquidity exists but almost nothing traded in 24h: the price may be stale, so FDV is not shown." },
};

export function SegmentTable({ projects, config, networkGas, startRank = 1 }: {
  projects: ProjectSummary[];
  config: SegmentConfig;
  networkGas: number | null;
  startRank?: number;
}) {
  if (projects.length === 0) {
    return <div className="iso-table-wrap"><div className="iso-dim" style={{ padding: 24 }}>Nothing tracked in this group yet.</div></div>;
  }
  const maxes = Object.fromEntries(
    config.columns.map((k) => [k, Math.max(0, ...projects.map((p) => metricOf(p, k, networkGas) ?? 0))]),
  ) as Record<ColumnKey, number>;

  return (
    <div className="iso-table-wrap">
      <table className="iso-table">
        <thead>
          <tr>
            <th>project</th>
            {config.columns.map((k) => <th key={k}>{COLUMN_LABELS[k]}</th>)}
          </tr>
        </thead>
        <tbody>
          {projects.map((p, i) => (
            <tr key={p.id} style={{ animationDelay: `${Math.min(i, 12) * 35}ms` }}>
              <td>
                <Link href={`/projects/${p.id}`} className="iso-cell-main">
                  <span className="iso-rank">{startRank + i}</span>
                  <Avatar name={p.name} />
                  <span style={{ minWidth: 0 }}>
                    <span style={{ fontWeight: 600, display: "block", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</span>
                    <span className="iso-pill" style={{ marginTop: 3 }}>{p.category ?? "unclassified"}</span>
                    {p.tier === "curated" && <span className="iso-pill good" style={{ marginLeft: 6 }}>verified</span>}
                    {p.market?.listed_on_coingecko && <span className="iso-pill good" style={{ marginLeft: 6 }} title="Mapped to a CoinGecko listing">CoinGecko</span>}
                  </span>
                </Link>
              </td>
              {config.columns.map((k) => {
                const v = metricOf(p, k, networkGas);
                if (k === "failed") {
                  return <td key={k}><span className={`iso-pill ${failedTone(v)}`}>{cell(k, p, networkGas)}</span></td>;
                }
                if (k === "price") {
                  const note = p.market ? QUALITY_NOTE[p.market.quality] : undefined;
                  return (
                    <td key={k} className="iso-num" style={note ? { opacity: 0.8 } : undefined}>
                      {cell(k, p, networkGas)}
                      {note && <span className="iso-pill warn" style={{ marginLeft: 6 }} title={note.title}>{note.label}</span>}
                    </td>
                  );
                }
                if (k === "fdv" && v === null && p.market) {
                  return <td key={k} className="iso-num iso-dim" title="Not shown: FDV is only meaningful when the price is backed by real liquidity and trading.">—</td>;
                }
                if (k === "score") {
                  return <td key={k} className="iso-num" style={{ color: "var(--accent)" }}>{cell(k, p, networkGas)}</td>;
                }
                const primary = k === config.sortBy;
                const w = v !== null && maxes[k] > 0 ? Math.max(2, (v / maxes[k]) * 100) : 0;
                return (
                  <td
                    key={k}
                    className={`iso-num ${primary ? "iso-bartd" : ""}`}
                    style={primary ? ({ ["--w" as string]: `${w}%`, ["--bar" as string]: "rgba(255,91,46,.2)" } as React.CSSProperties) : undefined}
                  >
                    {cell(k, p, networkGas)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

