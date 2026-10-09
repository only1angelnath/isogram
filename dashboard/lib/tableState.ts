// tableState.ts - server-side sort + pagination state for every list table.
//
// State lives in the URL (?sort=tx&dir=desc&page=2) so tables stay server-rendered, links are
// shareable, and nothing needs client JS. Sorting always runs over the FULL list before it is
// cut into pages, so "page 2 of a descending sort" really is rows 51-100 of the whole set.

export const PAGE_SIZE = 50;

export type SortDir = "asc" | "desc";
export type Query = Record<string, string | undefined>;

/** Next hands repeated params over as arrays; take the first string, ignore anything else. */
export function firstParam(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  return undefined;
}

export interface SortState {
  key: string;
  dir: SortDir;
}

/** Only keys in `allowed` are honoured, so a hand-edited URL can never sort by something odd. */
export function parseSort(rawSort: unknown, rawDir: unknown, allowed: readonly string[], fallback: SortState): SortState {
  const key = firstParam(rawSort);
  if (!key || !allowed.includes(key)) return fallback;
  const dir = firstParam(rawDir);
  return { key, dir: dir === "asc" || dir === "desc" ? dir : key === "name" ? "asc" : "desc" };
}

export function parsePage(raw: unknown): number {
  const n = Number.parseInt(firstParam(raw) ?? "", 10);
  return Number.isFinite(n) && n >= 1 ? n : 1;
}

export interface Paged<T> {
  rows: T[];
  page: number;
  pages: number;
  total: number;
  /** 1-based position of the first / last row on this page (0 when empty). */
  from: number;
  to: number;
}

export function paginate<T>(rows: readonly T[], requestedPage: number, size: number = PAGE_SIZE): Paged<T> {
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / size));
  const page = Math.min(Math.max(1, requestedPage), pages);
  const start = (page - 1) * size;
  const slice = rows.slice(start, start + size);
  return { rows: slice, page, pages, total, from: slice.length ? start + 1 : 0, to: start + slice.length };
}

/** "/projects" + {segment:"token", sort:undefined} -> "/projects?segment=token". */
export function href(base: string, query: Query): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== "") params.set(k, v);
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

/** Page numbers to show: first, last, and a window around the current page, with gaps as null. */
export function pageWindow(page: number, pages: number): (number | null)[] {
  const keep = new Set<number>([1, pages, page - 2, page - 1, page, page + 1, page + 2]);
  const sorted = [...keep].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const out: (number | null)[] = [];
  sorted.forEach((n, i) => {
    if (i > 0 && n - sorted[i - 1] > 1) out.push(null);
    out.push(n);
  });
  return out;
}
