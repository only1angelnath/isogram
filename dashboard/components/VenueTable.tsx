import Link from "next/link";
import { formatPercent, formatUsd, formatUsdCompact } from "@/lib/format";
import { Query, SortDir, href } from "@/lib/tableState";
import { Venue } from "@/lib/types";
import { VenueSortKey } from "@/lib/venues";

const COLUMNS: { key: VenueSortKey; label: string; title?: string }[] = [
  { key: "kind", label: "type", title: "DEX, or a launch platform (a venue where new tokens are created and first traded)." },
  { key: "volume", label: "24h volume", title: "Summed over the venue's busiest pools (GeckoTerminal, third-party), after leaving out anomalous pools: fewer than 10 traders in 24h, or volume above 25x reserves. The excluded amount is shown under the figure." },
  { key: "share", label: "share", title: "Fraction of the volume of all venues listed here." },
  { key: "pools", label: "active pools", title: "Pools with trading in the last 24h, among the pools scanned." },
  { key: "top", label: "most traded pool" },
];

function SortTh({ label, colKey, title, sort }: { label: string; colKey: VenueSortKey; title?: string; sort: { basePath: string; query: Query; key: VenueSortKey; dir: SortDir } }) {
  const active = sort.key === colKey;
  const nextDir: SortDir = active ? (sort.dir === "desc" ? "asc" : "desc") : colKey === "name" || colKey === "kind" ? "asc" : "desc";
  return (
    <th aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"} title={title}>
      <Link href={href(sort.basePath, { ...sort.query, sort: colKey, dir: nextDir })} className={`iso-sort${active ? " on" : ""}`} prefetch={false}>
        {label}
        <span aria-hidden="true">{active ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}</span>
      </Link>
    </th>
  );
}

export function VenueTable({ venues, startRank = 1, sort }: {
  venues: Venue[];
  startRank?: number;
  sort: { basePath: string; query: Query; key: VenueSortKey; dir: SortDir };
}) {
  if (venues.length === 0) {
    return <div className="iso-table-wrap"><div className="iso-dim" style={{ padding: 24 }}>No venues with trading volume in this group right now.</div></div>;
  }
  return (
    <>
    <div className="iso-mlist">
      {venues.map((v, i) => (
        <div key={v.dex_id} className="iso-mrow flat">
          <span className="who">
            <span className="top"><span className="nm">{v.name}</span><span className={`iso-pill${v.kind === "launchpad" ? " good" : ""}`}>{v.kind === "launchpad" ? "launch" : "dex"}</span></span>
            <span className="meta">#{startRank + i}{v.top_pool_name ? ` · top pool ${v.top_pool_name}` : ""}</span>
          </span>
          <span className="val">{v.truncated ? "≥ " : ""}{formatUsdCompact(v.volume_24h_usd)}<small>24h volume</small></span>
          <span className="mstats" style={{ ["--n" as string]: 3 }}>
            <span className="mstat"><i>share</i><b>{formatPercent(v.share)}</b></span>
            <span className="mstat"><i>active pools</i><b>{v.active_pools.toLocaleString("en-US")}</b></span>
            <span className="mstat"><i>excluded</i><b>{v.excluded_volume_usd > 0 ? formatUsdCompact(v.excluded_volume_usd) : "—"}</b></span>
          </span>
        </div>
      ))}
    </div>
    <div className="iso-table-wrap has-list">
      <table className="iso-table">
        <thead>
          <tr>
            <SortTh label="venue" colKey="name" sort={sort} />
            {COLUMNS.map((c) => <SortTh key={c.key} label={c.label} colKey={c.key} title={c.title} sort={sort} />)}
          </tr>
        </thead>
        <tbody>
          {venues.map((v, i) => (
            <tr key={v.dex_id}>
              <td>
                <span className="iso-cell-main">
                  <span className="iso-rank">{startRank + i}</span>
                  <span>{v.name}</span>
                </span>
              </td>
              <td><span className={`iso-pill${v.kind === "launchpad" ? " good" : ""}`}>{v.kind === "launchpad" ? "launch venue" : "dex"}</span></td>
              <td className="iso-num" style={{ color: "var(--accent)" }}>
                <span title={v.truncated ? "Lower bound: this venue has more pools than the scan covers." : undefined}>
                  {v.truncated ? "≥ " : ""}{formatUsd(v.volume_24h_usd)}
                </span>
                {v.excluded_volume_usd > 0 && (
                  <div className="iso-dim" style={{ fontSize: 11 }}
                    title={`${v.excluded_pools} pool(s) left out as anomalous: fewer than 10 traders in 24h, or volume above 25x their reserves.`}>
                    +{formatUsdCompact(v.excluded_volume_usd)} excluded
                  </div>
                )}
              </td>
              <td className="iso-num">{formatPercent(v.share)}</td>
              <td className="iso-num">{v.active_pools.toLocaleString("en-US")}</td>
              <td className="iso-num iso-dim">
                {v.top_pool_name ? <>{v.top_pool_name} · {formatUsdCompact(v.top_pool_volume_usd)}</> : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}
