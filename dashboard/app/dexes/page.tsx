import Link from "next/link";
import { listVenues } from "@/lib/api";
import { VenueTable } from "@/components/VenueTable";
import { Pagination } from "@/components/Pagination";
import { formatRelativeAge, formatUsdCompact } from "@/lib/format";
import { firstParam, paginate, parsePage, parseSort } from "@/lib/tableState";
import { VENUE_SORT_KEYS, VenueKind, VenueSortKey, filterVenues, parseKind, sortVenues, totalVolume } from "@/lib/venues";

export const dynamic = "force-dynamic";

const KINDS: { id: VenueKind; label: string }[] = [
  { id: "all", label: "All venues" },
  { id: "dex", label: "DEXes" },
  { id: "launchpad", label: "Launch venues" },
];

export default async function DexesPage({ searchParams }: {
  searchParams: Promise<{ kind?: string; sort?: string; dir?: string; page?: string }>;
}) {
  const sp = await searchParams;
  const venues = await listVenues();
  const kind = parseKind(firstParam(sp.kind));
  const all = venues ?? [];
  const selected = filterVenues(all, kind);
  const sortState = parseSort(sp.sort, sp.dir, VENUE_SORT_KEYS, { key: "volume", dir: "desc" });
  const sorted = sortVenues(selected, sortState.key as VenueSortKey, sortState.dir);
  const paged = paginate(sorted, parsePage(sp.page));
  const customSort = sortState.key !== "volume" || sortState.dir !== "desc";
  const baseQuery = { kind: kind === "all" ? undefined : kind };
  const newest = all.map((v) => v.fetched_at).sort().pop() ?? null;

  return (
    <main className="container section">
      <div className="eyebrow">DEXES &amp; LAUNCH VENUES</div>
      <h2 style={{ fontSize: 32, marginBottom: 12 }}>Where trading happens on Arc.</h2>
      <p className="lede">
        24-hour trading volume for every DEX and launch platform with activity. Uniswap V2, V3 and V4 are listed
        separately, as GeckoTerminal and CoinGecko list them. This is third-party market data, not read from the chain.
      </p>

      <div className="iso-cards" style={{ marginTop: 28 }}>
        {KINDS.map((k, i) => {
          const items = filterVenues(all, k.id);
          return (
            <Link key={k.id} href={k.id === "all" ? "/dexes" : `/dexes?kind=${k.id}`} className="iso-card" aria-current={k.id === kind ? "page" : undefined} style={{ animationDelay: `${i * 60}ms` }}>
              <div className="k">{k.label}</div>
              <div className="big">{formatUsdCompact(totalVolume(items))}</div>
              <div className="sub">{items.length} venues · 24h volume</div>
            </Link>
          );
        })}
      </div>

      {venues === null ? (
        <div className="iso-table-wrap"><div className="iso-dim" style={{ padding: 24 }}>Venue data is temporarily unavailable. The rest of the dashboard is unaffected; try again in a minute.</div></div>
      ) : (
        <>
          <VenueTable
            venues={paged.rows}
            startRank={paged.from || 1}
            sort={{ basePath: "/dexes", query: baseQuery, key: sortState.key as VenueSortKey, dir: sortState.dir }}
          />
          <Pagination
            paged={paged}
            basePath="/dexes"
            query={{ ...baseQuery, sort: customSort ? sortState.key : undefined, dir: customSort ? sortState.dir : undefined }}
            noun="venues"
          />
        </>
      )}

      <p className="pt-note">
        Source: GeckoTerminal (via CoinGecko), refreshed hourly{newest ? `, last updated ${formatRelativeAge(newest)}` : ""}. Each venue&apos;s
        busiest pools are summed, <b>after leaving out anomalous pools</b>: those with fewer than 10 traders in 24 hours, or whose volume exceeds
        25&times; their reserves. On Arc a handful of such pools can otherwise report tens of millions of dollars from two or three wallets; the
        amount left out is shown under each figure, and CoinGecko&apos;s own filter is not public, so totals can differ from theirs. A leading &ldquo;&ge;&rdquo;
        means the venue has more pools than the scan covers. A <b>launch venue</b> is a confirmed launch platform; venues not yet confirmed
        as launch platforms are listed as DEXes. Click a column to sort.
      </p>
    </main>
  );
}
