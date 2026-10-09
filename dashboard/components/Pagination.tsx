import Link from "next/link";
import { Paged, Query, href, pageWindow } from "@/lib/tableState";

/** Prev / numbered / next links under a table. Renders nothing when everything fits on one page. */
export function Pagination({ paged, basePath, query, noun = "rows" }: {
  paged: Paged<unknown>;
  basePath: string;
  /** Everything except `page` (segment, sort, dir), carried across page links. */
  query: Query;
  noun?: string;
}) {
  if (paged.total === 0) return null;
  const link = (p: number) => href(basePath, { ...query, page: p > 1 ? String(p) : undefined });
  return (
    <nav className="iso-pager" aria-label="Table pages">
      <span className="iso-dim">
        {paged.from}–{paged.to} of {paged.total.toLocaleString()} {noun}
      </span>
      {paged.pages > 1 && (
        <span className="iso-pager-links">
          {paged.page > 1 ? <Link href={link(paged.page - 1)} rel="prev">← prev</Link> : <span className="off">← prev</span>}
          {pageWindow(paged.page, paged.pages).map((p, i) =>
            p === null ? (
              <span key={`gap${i}`} className="off">…</span>
            ) : (
              <Link key={p} href={link(p)} aria-current={p === paged.page ? "page" : undefined}>{p}</Link>
            ),
          )}
          {paged.page < paged.pages ? <Link href={link(paged.page + 1)} rel="next">next →</Link> : <span className="off">next →</span>}
        </span>
      )}
    </nav>
  );
}
