"use client";

// DiscoveredPanel.tsx - contracts discovery has seen. "Unclassified" is the work queue (busiest first),
// "Waiting for promotion" confirms a classification was saved, "Dismissed" is the undo-less trash.

import { useCallback, useEffect, useState } from "react";
import { Discovered, SessionExpiredError, adminFetch, errorText, timeAgo } from "@/components/admin/adminApi";
import { Addr } from "@/components/admin/ui";

type View = "unclassified" | "needs_review" | "rejected";
const LABEL: Record<View, string> = { unclassified: "Unclassified", needs_review: "Waiting for promotion", rejected: "Dismissed" };

export function DiscoveredPanel({ onExpired, onCount, onClassify }: {
  onExpired: () => void; onCount: (n: number) => void; onClassify: (address: string, name: string) => void;
}) {
  const [view, setView] = useState<View>("unclassified");
  const [rows, setRows] = useState<Discovered[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await adminFetch<Discovered[]>(`discovered?status=${view}&limit=100`);
      setRows(data);
      setError(null);
      if (view === "unclassified") onCount(data.length);
    } catch (e) {
      if (e instanceof SessionExpiredError) onExpired();
      else setError(errorText(e, "Could not load contracts."));
    }
  }, [view, onExpired, onCount]);

  useEffect(() => { setRows(null); load(); }, [load]);

  async function dismiss(address: string) {
    if (!window.confirm("Dismiss this contract? It will not be tracked.")) return;
    setBusy(address);
    try {
      await adminFetch(`discovered/${address}/reject`, { method: "POST" });
      await load();
    } catch (e) {
      if (e instanceof SessionExpiredError) onExpired();
      else setError(errorText(e, "Could not dismiss it."));
    } finally {
      setBusy(null);
    }
  }

  async function restore(address: string) {
    setBusy(address);
    try {
      await adminFetch(`discovered/${address}/restore`, { method: "POST" });
      await load();
    } catch (e) {
      if (e instanceof SessionExpiredError) onExpired();
      else setError(errorText(e, "Could not restore it."));
    } finally {
      setBusy(null);
    }
  }

  const q = filter.trim().toLowerCase();
  const shown = (rows ?? []).filter((r) => !q || r.contract_address.toLowerCase().includes(q) || (r.gecko_name ?? "").toLowerCase().includes(q));

  return (
    <section aria-labelledby="disc-h">
      <div className="adm-bar">
        <h2 id="disc-h">Discovered contracts</h2>
        <div className="adm-seg" role="group" aria-label="Show">
          {(Object.keys(LABEL) as View[]).map((v) => (
            <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}>{LABEL[v]}</button>
          ))}
        </div>
      </div>
      <p className="iso-dim adm-sub">
        {view === "unclassified" && "Busy contracts that no source could identify, most active first. Classify the real ones, dismiss the junk."}
        {view === "needs_review" && "Classified and queued. They become projects on the next discovery run."}
        {view === "rejected" && "Dismissed by you, or rejected automatically (for example look-alike names). Restoring sends a contract back to Unclassified for a fresh decision."}
      </p>
      <input className="adm-search" type="search" placeholder="Filter by address or name" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter contracts" />
      {error && <p className="kf-error" role="alert">{error}</p>}
      {rows === null && !error && <p className="iso-dim">Loading…</p>}
      {rows && shown.length === 0 && <p className="iso-dim">{rows.length === 0 ? "Nothing here right now." : "No match for that filter."}</p>}
      <div className="adm-list">
        {shown.map((c) => (
          <article key={c.contract_address} className="panel adm-card compact">
            <header className="adm-card-head">
              <div>
                <h3>{c.gecko_name || c.gecko_symbol || "Unknown contract"} {c.category && <span className="adm-chip">{c.category}</span>}</h3>
                <Addr address={c.contract_address} />
              </div>
              <span className="adm-time">last seen {timeAgo(c.last_seen)}</span>
            </header>
            <p className="adm-stats"><b className="mono">{c.call_count.toLocaleString("en-US")}</b> calls · first seen {timeAgo(c.first_seen)}</p>
            {view === "rejected" ? (
              <div className="adm-actions">
                <button type="button" className="btn-ghost adm-ghost" disabled={busy === c.contract_address} onClick={() => restore(c.contract_address)}>{busy === c.contract_address ? "Restoring…" : "Restore"}</button>
              </div>
            ) : (
              <div className="adm-actions">
                <button type="button" className="btn" onClick={() => onClassify(c.contract_address, c.gecko_name ?? "")}>{view === "needs_review" ? "Reclassify" : "Classify"}</button>
                <button type="button" className="btn-ghost adm-ghost" disabled={busy === c.contract_address} onClick={() => dismiss(c.contract_address)}>{busy === c.contract_address ? "Dismissing…" : "Dismiss"}</button>
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
