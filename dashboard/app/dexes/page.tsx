import Link from "next/link";
import type { Metadata } from "next";
import { listVenues } from "@/lib/api";
import { VenueTable } from "@/components/VenueTable";
import { Pagination } from "@/components/Pagination";
import { formatRelativeAge, formatUsdCompact } from "@/lib/format";
import { firstParam, paginate, parsePage, parseSort } from "@/lib/tableState";
import { VENUE_SORT_KEYS, VenueKind, VenueSortKey, filterVenues, parseKind, sortVenues, totalVolume } from "@/lib/venues";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "DEXes" };

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
    <main className="container section first">
      <div className="page-head">
        <div className="eyebrow">DEXes</div>
        <h1>Where trading happens on Arc.</h1>
        <p className="lede">24h volume for every DEX and launch platform with activity. Third-party data, not read from the chain.</p>
      </div>

      <div className="iso-cards compact">
        {KINDS.map((k) => {
          const items = filterVenues(all, k.id);
          return (
            <Link key={k.id} href={k.id === "all" ? "/dexes" : `/dexes?kind=${k.id}`} className="iso-card" aria-current={k.id === kind ? "page" : undefined}>
              <div className="k">{k.label}</div>
              <div className="big">{formatUsdCompact(totalVolume(items))}</div>
              <div className="sub">{items.length} venues</div>
            </Link>
          );
        })}
      </div>

      {venues === null ? (
        <div className="iso-table-wrap"><div className="iso-dim" style={{ padding: 24 }}>Venue data is temporarily unavailable. Try again in a minute.</div></div>
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
        GeckoTerminal, refreshed hourly{newest ? `, updated ${formatRelativeAge(newest)}` : ""}. Anomalous pools are left out and shown as &ldquo;excluded&rdquo;;
        &ldquo;&ge;&rdquo; marks a lower bound. <Link href="/methodology#venues">Details</Link>
      </p>
    </main>
  );
}
