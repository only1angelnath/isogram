"use client";

// ClassifyPanel.tsx - set a contract's category by hand. Clicking "Classify" on a discovered contract
// prefills this form. The category list comes from the API, so it can never drift from what the
// pipeline accepts; the API validates it again.

import { FormEvent, useEffect, useState } from "react";
import { ADDRESS_RE, CategoryRow, SessionExpiredError, adminFetch, errorText } from "@/components/admin/adminApi";
import { CategorySelect, Consequence, TrackedBadge } from "@/components/admin/ui";

export interface Prefill { address: string; name: string; nonce: number }

export function ClassifyPanel({ categories, prefill, onExpired, onSaved }: {
  categories: CategoryRow[]; prefill: Prefill | null; onExpired: () => void; onSaved: () => void;
}) {
  const [address, setAddress] = useState("");
  const [category, setCategory] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!prefill) return;
    setAddress(prefill.address);
    setName(prefill.name);
    setCategory("");
    setMessage(null);
    setError(null);
  }, [prefill]);

  const addr = address.trim();
  const valid = ADDRESS_RE.test(addr);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!valid || !category) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await adminFetch("classify", { method: "POST", body: JSON.stringify({ contract_address: addr, category, name: name.trim() || null }) });
      setMessage(`Saved ${name.trim() || addr} as ${category}. It becomes a project on the next discovery run; check "Waiting for promotion" under Discovered.`);
      setAddress(""); setCategory(""); setName("");
      onSaved();
    } catch (err) {
      if (err instanceof SessionExpiredError) onExpired();
      else setError(errorText(err, "Could not save."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="cls-h">
      <div className="adm-bar"><h2 id="cls-h">Classify a contract</h2></div>
      <p className="iso-dim adm-sub">Use this for a contract the pipeline missed or got wrong. It is queued, not made live at once: promotion happens on the next scheduled discovery run.</p>
      <form className="panel adm-card adm-formcard" onSubmit={save}>
        <div className="adm-field wide">
          <label htmlFor="cls-address">Contract address</label>
          <input id="cls-address" className="mono" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="0x…" spellCheck={false} autoComplete="off" maxLength={42} aria-invalid={addr.length > 0 && !valid} />
          {addr.length > 0 && !valid && <p className="adm-hint">0x followed by 40 hex characters.</p>}
        </div>
        <TrackedBadge address={addr} />
        <div className="adm-field">
          <label htmlFor="cls-cat">Category</label>
          <CategorySelect id="cls-cat" value={category} onChange={setCategory} categories={categories} />
        </div>
        <div className="adm-field">
          <label htmlFor="cls-name">Project name (optional)</label>
          <input id="cls-name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} autoComplete="off" />
        </div>
        <Consequence category={category} categories={categories} />
        {error && <p className="kf-error" role="alert">{error}</p>}
        {message && <p className="adm-ok" role="status">{message}</p>}
        <div className="adm-actions">
          <button type="submit" className="btn" disabled={busy || !valid || !category}>{busy ? "Saving…" : "Save classification"}</button>
        </div>
      </form>
    </section>
  );
}
