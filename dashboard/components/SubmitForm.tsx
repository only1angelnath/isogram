"use client";

// SubmitForm.tsx - propose a contract for listing. Posts straight from the browser to POST /submit (not through a Next
// route) so the API's per-address submission limit sees the visitor's own address. Nothing is listed automatically:
// every submission lands in a human review queue. A pasted address is first checked against what is already tracked.

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/;
const CATEGORIES = ["DeFi protocol", "Token", "Stablecoin", "Launchpad", "Infrastructure", "NFT", "Other"];

interface Tracked { id: string; name: string }

export function SubmitForm({ apiBase }: { apiBase: string }) {
  const [address, setAddress] = useState("");
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [website, setWebsite] = useState("");
  const [x, setX] = useState("");
  const [contact, setContact] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [tracked, setTracked] = useState<Tracked | null>(null);

  const addr = address.trim();
  const validAddress = ADDRESS_RE.test(addr);

  // Already tracked? Silent on any failure: the check is a courtesy, the API is the authority.
  useEffect(() => {
    setTracked(null);
    if (!validAddress) return;
    let cancelled = false;
    fetch(`/api/search?address=${addr}`)
      .then((r) => (r.ok ? (r.json() as Promise<Tracked>) : null))
      .then((t) => { if (!cancelled && t && t.id) setTracked(t); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [addr, validAddress]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!validAddress || tracked) return;
    setBusy(true);
    setError(null);
    const socials: Record<string, string> = {};
    if (website.trim()) socials.website = website.trim();
    if (x.trim()) socials.x = x.trim();
    try {
      const res = await fetch(`${apiBase}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contract_address: addr,
          proposed_name: name.trim() || null,
          proposed_category: category || null,
          socials: Object.keys(socials).length ? socials : null,
          submitter_contact: contact.trim() || null,
          note: note.trim() || null,
        }),
      });
      if (res.status === 201) { setDone(true); return; }
      if (res.status === 429) {
        const wait = Number(res.headers.get("Retry-After"));
        setError(`Too many submissions from this address.${wait > 0 ? ` Try again in about ${Math.max(1, Math.ceil(wait / 60))} min.` : " Try again later."}`);
      } else if (res.status === 422) {
        setError("Check the contract address (0x followed by 40 hex characters) and keep each field under 500 characters.");
      } else {
        setError("Could not send this right now. Try again in a minute.");
      }
    } catch {
      setError("Could not reach the API. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="panel keyform wide">
        <h3>Thanks, it is in the queue.</h3>
        <p className="iso-dim" style={{ margin: "0 0 12px" }}>
          A person reviews every submission before anything is listed, so it will not appear straight away. Contracts with real activity on Arc are the easiest to confirm.
        </p>
        <button type="button" className="btn-ghost" style={{ background: "none", cursor: "pointer" }} onClick={() => { setDone(false); setAddress(""); setName(""); setCategory(""); setWebsite(""); setX(""); setContact(""); setNote(""); }}>Submit another</button>
      </div>
    );
  }

  return (
    <form className="panel keyform wide" onSubmit={submit}>
      <label htmlFor="sf-address" style={{ marginTop: 0 }}>Contract address *</label>
      <input id="sf-address" className="mono" required value={address} onChange={(e) => setAddress(e.target.value)} placeholder="0x…" spellCheck={false} autoComplete="off" maxLength={42} aria-invalid={addr.length > 0 && !validAddress} />
      {addr.length > 0 && !validAddress && <p className="kf-hint">An address is 0x followed by 40 hex characters.</p>}
      {tracked && (
        <p className="kf-ok" role="status">
          Already tracked as <Link href={`/projects/${encodeURIComponent(tracked.id)}`}>{tracked.name}</Link>. No need to submit it.
        </p>
      )}

      <label htmlFor="sf-name">Project name</label>
      <input id="sf-name" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Swap" autoComplete="off" />

      <label htmlFor="sf-cat">Type</label>
      <select id="sf-cat" value={category} onChange={(e) => setCategory(e.target.value)}>
        <option value="">Not sure</option>
        {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>

      <label htmlFor="sf-web">Website</label>
      <input id="sf-web" type="url" maxLength={200} value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://" autoComplete="off" />

      <label htmlFor="sf-x">X handle</label>
      <input id="sf-x" maxLength={60} value={x} onChange={(e) => setX(e.target.value)} placeholder="@acmeswap" autoComplete="off" />

      <label htmlFor="sf-contact">How can we reach you?</label>
      <input id="sf-contact" maxLength={200} value={contact} onChange={(e) => setContact(e.target.value)} placeholder="Email or Telegram" autoComplete="off" />
      <p className="kf-hint">Optional. Only used if the reviewer has a question. Never shown publicly.</p>

      <label htmlFor="sf-note">Anything the reviewer should know?</label>
      <textarea id="sf-note" rows={3} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What the contract does, or which of your contracts are related." />

      {error && <p className="kf-error" role="alert">{error}</p>}
      <button type="submit" className="btn" disabled={busy || !validAddress || !!tracked}>{busy ? "Sending…" : "Submit for review"}</button>
    </form>
  );
}
