"use client";

// KeysPanel.tsx - API keys: who has one, when it was last used, revoke. Only the prefix is ever
// shown (the key itself is stored as a hash and cannot be recovered). Emails are for follow-up.

import { useCallback, useEffect, useState } from "react";
import { KeyRow, SessionExpiredError, adminFetch, errorText, timeAgo } from "@/components/admin/adminApi";
import { CopyButton } from "@/components/admin/ui";
import { toCsv } from "@/lib/csv";

export function KeysPanel({ onExpired, onCount }: { onExpired: () => void; onCount: (n: number) => void }) {
  const [rows, setRows] = useState<KeyRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [showRevoked, setShowRevoked] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await adminFetch<KeyRow[]>("keys");
      setRows([...data].sort((a, b) => b.id - a.id));
      setError(null);
      onCount(data.filter((k) => !k.revoked_at).length);
    } catch (e) {
      if (e instanceof SessionExpiredError) onExpired();
      else setError(errorText(e, "Could not load keys."));
    }
  }, [onExpired, onCount]);

  useEffect(() => { load(); }, [load]);

  async function revoke(k: KeyRow) {
    if (!window.confirm(`Revoke ${k.key_prefix}… (${k.name})? Requests using it get 401 straight away.`)) return;
    setBusy(k.id);
    try {
      await adminFetch(`keys/${k.id}/revoke`, { method: "POST" });
      await load();
    } catch (e) {
      if (e instanceof SessionExpiredError) onExpired();
      else setError(errorText(e, "Could not revoke it."));
    } finally {
      setBusy(null);
    }
  }

  const q = filter.trim().toLowerCase();
  const all = rows ?? [];
  const active = all.filter((k) => !k.revoked_at);
  const shown = all.filter((k) => (showRevoked || !k.revoked_at) && (!q || `${k.name} ${k.email ?? ""} ${k.key_prefix}`.toLowerCase().includes(q)));
  const emails = [...new Set(active.map((k) => (k.email ?? "").trim()).filter(Boolean))];

  function downloadCsv() {
    const csv = toCsv(
      ["id", "key_prefix", "name", "email", "tier", "rate_limit_per_minute", "created_at", "last_used_at", "revoked_at"],
      all.map((k) => [k.id, k.key_prefix, k.name, k.email, k.tier, k.rate_limit_per_minute, k.created_at, k.last_used_at, k.revoked_at]),
    );
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url; a.download = "isogram-api-keys.csv"; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section aria-labelledby="key-h">
      <div className="adm-bar">
        <h2 id="key-h">API keys</h2>
        <div className="adm-tools">
          <CopyButton text={emails.join(", ")} label={`Copy ${emails.length} active emails`} />
          <button type="button" className="adm-mini" onClick={downloadCsv} disabled={all.length === 0}>Download CSV</button>
        </div>
      </div>
      <p className="iso-dim adm-sub">{active.length} active of {all.length}. Keys are stored as hashes; only the first characters are shown. The CSV and the copied emails contain personal data: keep them private.</p>
      <div className="adm-filterrow">
        <input className="adm-search" type="search" placeholder="Filter by name, email or key prefix" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter keys" />
        <label className="adm-check"><input type="checkbox" checked={showRevoked} onChange={(e) => setShowRevoked(e.target.checked)} /> Show revoked</label>
      </div>
      {error && <p className="kf-error" role="alert">{error}</p>}
      {rows === null && !error && <p className="iso-dim">Loading…</p>}
      {rows && shown.length === 0 && <p className="iso-dim">{all.length === 0 ? "No keys yet." : "No match."}</p>}
      <div className="adm-list">
        {shown.map((k) => (
          <article key={k.id} className={`panel adm-card compact${k.revoked_at ? " dim" : ""}`}>
            <header className="adm-card-head">
              <div>
                <h3>{k.name} <span className={`adm-chip ${k.revoked_at ? "bad" : "good"}`}>{k.revoked_at ? "revoked" : "active"}</span> <span className="adm-chip">{k.tier}</span></h3>
                <p className="adm-stats"><code className="mono">{k.key_prefix}…</code> · {k.email || "no email"}</p>
              </div>
              <span className="adm-time">created {timeAgo(k.created_at)}</span>
            </header>
            <p className="adm-stats">Last used: {k.revoked_at ? `revoked ${timeAgo(k.revoked_at)}` : timeAgo(k.last_used_at)} · {k.rate_limit_per_minute ?? "default"} req/min</p>
            {!k.revoked_at && (
              <div className="adm-actions">
                <button type="button" className="btn-ghost adm-ghost" disabled={busy === k.id} onClick={() => revoke(k)}>{busy === k.id ? "Revoking…" : "Revoke"}</button>
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
