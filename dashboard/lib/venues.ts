// venues.ts - filtering and sorting for the DEXes page (pure, so it can be checked without a browser).

import { SortDir } from "./tableState";
import { Venue } from "./types";

export type VenueKind = "all" | "dex" | "launchpad";
export type VenueSortKey = "name" | "kind" | "volume" | "share" | "pools" | "top";

export const VENUE_SORT_KEYS: readonly VenueSortKey[] = ["name", "kind", "volume", "share", "pools", "top"];

export function parseKind(raw: unknown): VenueKind {
  const v = typeof raw === "string" ? raw : Array.isArray(raw) && typeof raw[0] === "string" ? raw[0] : "";
  return v === "dex" || v === "launchpad" ? v : "all";
}

export function filterVenues(venues: readonly Venue[], kind: VenueKind): Venue[] {
  return kind === "all" ? [...venues] : venues.filter((v) => v.kind === kind);
}

function valueOf(v: Venue, key: Exclude<VenueSortKey, "name" | "kind">): number | null {
  switch (key) {
    case "volume": return v.volume_24h_usd;
    case "share": return v.share;
    case "pools": return v.active_pools;
    case "top": return v.top_pool_volume_usd;
  }
}

/** Unknown values (a venue with no top pool) always sort last; ties fall back to volume, then name. */
export function sortVenues(venues: readonly Venue[], key: VenueSortKey, dir: SortDir): Venue[] {
  const sign = dir === "asc" ? 1 : -1;
  const tie = (a: Venue, b: Venue) => b.volume_24h_usd - a.volume_24h_usd || a.name.localeCompare(b.name);
  return [...venues].sort((a, b) => {
    if (key === "name") return sign * a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) || tie(a, b);
    if (key === "kind") return sign * a.kind.localeCompare(b.kind) || tie(a, b);
    const av = valueOf(a, key);
    const bv = valueOf(b, key);
    if (av === null && bv !== null) return 1;
    if (bv === null && av !== null) return -1;
    return sign * ((av ?? 0) - (bv ?? 0)) || tie(a, b);
  });
}

export function totalVolume(venues: readonly Venue[]): number {
  return venues.reduce((sum, v) => sum + v.volume_24h_usd, 0);
}
