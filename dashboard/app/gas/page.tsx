import Link from "next/link";
import { getNetworkDaily, listProjects } from "@/lib/api";
import { SegmentTable } from "@/components/SegmentTable";
import { Pagination } from "@/components/Pagination";
import { Avatar } from "@/components/Avatar";
import { ColumnKey, SEGMENTS, SegmentConfig, rankProjects, sortProjects, sumGas } from "@/lib/segments";
import { paginate, parsePage, parseSort } from "@/lib/tableState";
import { formatCount, formatPercent, formatUsd } from "@/lib/format";

export const dynamic = "force-dynamic";

// The gas leaderboard shows only projects that actually consumed gas: gas is paid by whoever
// CALLS a contract, so a token nobody transacted with, or a contract that is only ever read,
// has none. Ranking everything by gas would just list zeros.
const GAS_VIEW: SegmentConfig = {
  id: "infra",
  label: "Gas leaderboard",
  short: "Gas",
  blurb: "",
  columns: ["gas", "share", "tx", "users", "failed"],
  sortBy: "gas",
  showsScore: false,
  showsTvl: false,
};

export default async function GasLeaderboardPage({ searchParams }: {
  searchParams: Promise<{ segment?: string; sort?: string; dir?: string; page?: string }>;
}) {
  const sp = await searchParams;
  const segment = sp.segment;
  const [all, days] = await Promise.all([listProjects(), getNetworkDaily(7)]);
  const networkGas = sumGas(days);

  const payers = all.filter((p) => (p.usdc_gas_7d ?? 0) > 0);
  const counts = SEGMENTS.map((s) => ({ s, n: payers.filter((p) => (p.segment ?? "other") === s.id).length })).filter((x) => x.n > 0);
  const filtered = segment && counts.some((c) => c.s.id === segment) ? payers.filter((p) => (p.segment ?? "other") === segment) : payers;
  const ranked = rankProjects(filtered, "gas", networkGas);
  const podium = ranked.slice(0, 3);
  // The podium highlights the top three by gas; the table below lists EVERYONE, sortable and paged.
  const sortState = parseSort(sp.sort, sp.dir, ["name", ...GAS_VIEW.columns], { key: "gas", dir: "desc" });
  const sorted = sortProjects(filtered, sortState.key as ColumnKey | "name", sortState.dir, networkGas);
  const paged = paginate(sorted, parsePage(sp.page));
  const customSort = sortState.key !== "gas" || sortState.dir !== "desc";
  const tableQuery = { segment: segment && counts.some((c) => c.s.id === segment) ? segment : undefined };
  const pagerQuery = { ...tableQuery, sort: customSort ? sortState.key : undefined, dir: customSort ? sortState.dir : undefined };
  const attributed = payers.reduce((s, p) => s + (p.usdc_gas_7d ?? 0), 0);

  return (
    <main className="container section">
      <div className="eyebrow">GAS LEADERBOARD</div>
      <h2 style={{ fontSize: 32, marginBottom: 12 }}>Who is burning the most USDC gas.</h2>
      <p className="lede">
        Trailing 7 days. USDC is Arc&apos;s native gas asset, so this is Arc-native activity, not a proxy
        for it. Gas is paid by the people <i>calling</i> a contract — only {payers.length} of {all.length} tracked
        projects were called at all, and tokens, launchpads and infrastructure use gas very differently,
        so use the filters.
        {networkGas !== null && networkGas > 0 && <> Together they account for <b>{formatPercent(attributed / networkGas, 0)}</b> of all network gas.</>}
      </p>

      <div className="iso-tabs" style={{ marginTop: 22 }}>
        <Link href="/gas" className="iso-tab" aria-current={!segment || !counts.some((c) => c.s.id === segment) ? "page" : undefined}>All<small>{payers.length}</small></Link>
        {counts.map(({ s, n }) => (
          <Link key={s.id} href={`/gas?segment=${s.id}`} className="iso-tab" aria-current={segment === s.id ? "page" : undefined}>{s.short}<small>{n}</small></Link>
        ))}
      </div>

      {ranked.length === 0 ? (
        <p className="no-data">No gas recorded for this group yet.</p>
      ) : (
        <>
          <div className="iso-podium">
            {podium.map((p, i) => {
              const share = networkGas && p.usdc_gas_7d ? p.usdc_gas_7d / networkGas : null;
              return (
                <Link key={p.id} href={`/projects/${p.id}`} className="iso-card" style={{ animationDelay: `${i * 90}ms` }}>
                  <div className="place">#{i + 1}</div>
                  <div className="nm" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <Avatar name={p.name} />
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{p.name}</span>
                  </div>
                  <div className="big">{formatUsd(p.usdc_gas_7d, { decimals: (p.usdc_gas_7d ?? 0) < 10 ? 4 : 2 })}</div>
                  <div className="sub">{formatCount(p.tx_count_7d)} tx · {p.category ?? "unclassified"}{share !== null ? ` · ${formatPercent(share)} of network` : ""}</div>
                  <div className="iso-meter"><i style={{ width: `${Math.max(3, ((p.usdc_gas_7d ?? 0) / (podium[0].usdc_gas_7d || 1)) * 100)}%` }} /></div>
                </Link>
              );
            })}
          </div>
          <SegmentTable
            projects={paged.rows}
            config={GAS_VIEW}
            networkGas={networkGas}
            startRank={paged.from || 1}
            sort={{ basePath: "/gas", query: tableQuery, key: sortState.key, dir: sortState.dir }}
          />
          <Pagination paged={paged} basePath="/gas" query={pagerQuery} noun="projects" />
        </>
      )}
    </main>
  );
}

