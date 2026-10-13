"use client";

// KeyForm.tsx - self-service API key. Posts straight from the browser to the API (not through a Next
// route) so the API sees the visitor's own address for its per-address creation limit.

import { FormEvent, useState } from "react";
import { CodeBlock } from "@/components/CodeBlock";

interface Created { api_key: string; rate_limit_per_minute: number; name: string }

export function KeyForm({ apiBase }: { apiBase: string }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Created | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), email: email.trim() }),
      });
      if (res.status === 201) {
        setCreated((await res.json()) as Created);
        return;
      }
      if (res.status === 429) {
        const wait = res.headers.get("Retry-After");
        setError(`Too many keys created from this address today.${wait ? ` Try again in ${Math.ceil(Number(wait) / 3600)} h.` : ""}`);
      } else if (res.status === 409) {
        setError("This email already has the maximum number of active keys. Reuse one of them, or ask for one to be revoked.");
      } else if (res.status === 422) {
        setError("Check the project name (2 to 60 characters) and that the email looks like name@example.com.");
      } else {
        setError("Could not create a key right now. Try again in a minute.");
      }
    } catch {
      setError("Could not reach the API. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <div className="panel keyform">
        <h3>Your API key</h3>
        <p className="iso-dim" style={{ margin: "0 0 12px" }}>Copy it now. It is shown once and cannot be recovered; if you lose it, create another.</p>
        <CodeBlock code={created.api_key} />
        <p className="iso-dim" style={{ margin: "14px 0 8px" }}>Send it in the <code>X-API-Key</code> header ({created.rate_limit_per_minute} requests per minute):</p>
        <CodeBlock code={`curl -H "X-API-Key: ${created.api_key}" "${apiBase}/projects"`} />
        <button type="button" className="btn-ghost" style={{ marginTop: 14, background: "none", cursor: "pointer" }} onClick={() => { setCreated(null); setName(""); setEmail(""); }}>Create another</button>
      </div>
    );
  }

  return (
    <form className="panel keyform" onSubmit={submit}>
      <h3>Get a free API key</h3>
      <p className="iso-dim" style={{ margin: "0 0 14px" }}>600 requests per minute instead of 60. Free.</p>
      <label htmlFor="kf-name">What are you building?</label>
      <input id="kf-name" required minLength={2} maxLength={60} value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme portfolio tracker" autoComplete="off" />
      <label htmlFor="kf-email">Email</label>
      <input id="kf-email" type="email" required maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email" />
      <p className="kf-hint">Used only to contact you about the API: changes, limits and abuse. Not shown publicly and never sold.</p>
      {error && <p className="kf-error" role="alert">{error}</p>}
      <button type="submit" className="btn" disabled={busy || name.trim().length < 2 || !email.includes("@")}>{busy ? "Creating…" : "Create key"}</button>
    </form>
  );
}
