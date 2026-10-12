"use client";

// SearchBox.tsx - find a tracked project by name, symbol, id or category. The list is loaded once,
// on first focus, from /api/search (a slim server-side projection of /projects), so nothing is
// fetched for visitors who never search and the browser never needs the API's own URL.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

interface Item { id: string; name: string; category: string | null; tx: number }

const MAX = 8;

export function SearchBox({ idSuffix = "" }: { idSuffix?: string }) {
  const router = useRouter();
  const [items, setItems] = useState<Item[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(0);
  const loading = useRef(false);
  const box = useRef<HTMLDivElement>(null);

  async function load() {
    if (items || loading.current) return;
    loading.current = true;
    try {
      const res = await fetch("/api/search");
      if (!res.ok) throw new Error(String(res.status));
      setItems((await res.json()) as Item[]);
    } catch {
      setFailed(true);
      loading.current = false;
    }
  }

  const results = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t || !items) return [];
    const scored: { it: Item; rank: number }[] = [];
    for (const it of items) {
      const name = it.name.toLowerCase();
      const rank = name === t ? 0 : name.startsWith(t) ? 1 : name.includes(t) ? 2 : it.id.includes(t) ? 3 : (it.category ?? "").includes(t) ? 4 : -1;
      if (rank >= 0) scored.push({ it, rank });
    }
    scored.sort((a, b) => a.rank - b.rank || b.it.tx - a.it.tx);
    return scored.slice(0, MAX).map((s) => s.it);
  }, [q, items]);

  function go(it: Item | undefined) {
    if (!it) return;
    setOpen(false);
    setQ("");
    router.push(`/projects/${it.id}`);
  }

  const listId = `search-list${idSuffix}`;

  return (
    <div
      className="search"
      ref={box}
      onBlur={(e) => { if (!box.current?.contains(e.relatedTarget as Node | null)) setOpen(false); }}
    >
      <svg className="ico" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
        <circle cx="7" cy="7" r="4.6" /><path d="M10.5 10.5L14 14" />
      </svg>
      <input
        type="search"
        inputMode="search"
        autoComplete="off"
        spellCheck={false}
        placeholder="Search projects"
        aria-label="Search projects"
        aria-controls={listId}
        aria-expanded={open && q.trim() !== ""}
        value={q}
        onFocus={() => { setOpen(true); void load(); }}
        onChange={(e) => { setQ(e.target.value); setSel(0); setOpen(true); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, results.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
          else if (e.key === "Enter") { e.preventDefault(); go(results[sel]); }
          else if (e.key === "Escape") { setOpen(false); (e.target as HTMLInputElement).blur(); }
        }}
      />
      {open && q.trim() !== "" && (
        <div className="search-results" id={listId} role="listbox">
          {failed ? (
            <div className="empty">Search is unavailable right now.</div>
          ) : !items ? (
            <div className="empty">Loading…</div>
          ) : results.length === 0 ? (
            <div className="empty">No project matches “{q.trim()}”.</div>
          ) : (
            results.map((r, i) => (
              <Link key={r.id} href={`/projects/${r.id}`} role="option" aria-selected={i === sel}
                onClick={() => { setOpen(false); setQ(""); }} onMouseEnter={() => setSel(i)}>
                <span className="nm">{r.name}</span>
                <span className="iso-pill">{r.category ?? "unclassified"}</span>
              </Link>
            ))
          )}
        </div>
      )}
    </div>
  );
}
