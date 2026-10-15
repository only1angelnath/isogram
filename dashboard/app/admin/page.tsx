// app/admin/page.tsx - the curation desk. A client component: password gate, then four panels
// (submissions, discovered contracts, classify, API keys), all through /api/admin-proxy and never
// calling FastAPI's /admin/* directly (see that route for why).
"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { CategoryRow, SessionExpiredError, adminFetch } from "@/components/admin/adminApi";
import { SubmissionsPanel } from "@/components/admin/SubmissionsPanel";
import { DiscoveredPanel } from "@/components/admin/DiscoveredPanel";
import { ClassifyPanel, Prefill } from "@/components/admin/ClassifyPanel";
import { KeysPanel } from "@/components/admin/KeysPanel";

type Tab = "submissions" | "discovered" | "classify" | "keys";

export default function AdminPage() {
  const [authed, setAuthed] = useState(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loggingIn, setLoggingIn] = useState(false);

  const [tab, setTab] = useState<Tab>("submissions");
  const [categories, setCategories] = useState<CategoryRow[]>([]);
  const [counts, setCounts] = useState<{ submissions: number | null; discovered: number | null; keys: number | null }>({ submissions: null, discovered: null, keys: null });
  const [prefill, setPrefill] = useState<Prefill | null>(null);

  const expired = useCallback(() => {
    setAuthed(false);
    setLoginError("Session expired. Please log in again.");
  }, []);

  const setCount = useCallback((key: "submissions" | "discovered" | "keys") => (n: number) => setCounts((c) => (c[key] === n ? c : { ...c, [key]: n })), []);
  const onSubCount = useCallback((n: number) => setCount("submissions")(n), [setCount]);
  const onDiscCount = useCallback((n: number) => setCount("discovered")(n), [setCount]);
  const onKeyCount = useCallback((n: number) => setCount("keys")(n), [setCount]);

  useEffect(() => {
    if (!authed) return;
    adminFetch<CategoryRow[]>("categories")
      .then(setCategories)
      .catch((e) => { if (e instanceof SessionExpiredError) expired(); });
    // Counts for the tabs that are not open yet (the open Submissions panel reports its own).
    adminFetch<unknown[]>("discovered?status=unclassified&limit=100").then((r) => onDiscCount(r.length)).catch(() => {});
    adminFetch<{ revoked_at: string | null }[]>("keys").then((r) => onKeyCount(r.filter((k) => !k.revoked_at).length)).catch(() => {});
  }, [authed, expired, onDiscCount, onKeyCount]);

  async function handleLogin(e: FormEvent) {
    e.preventDefault();
    setLoggingIn(true);
    setLoginError(null);
    try {
      const res = await fetch("/api/admin-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || "Incorrect password");
      }
      setPassword("");
      setAuthed(true);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoggingIn(false);
    }
  }

  if (!authed) {
    return (
      <main className="container section first">
        <form className="panel keyform" onSubmit={handleLogin}>
          <h3>Isogram admin</h3>
          <label htmlFor="adm-pw">Password</label>
          <input id="adm-pw" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Admin password" autoFocus autoComplete="current-password" />
          {loginError && <p className="kf-error" role="alert">{loginError}</p>}
          <button type="submit" className="btn" disabled={loggingIn || !password}>{loggingIn ? "Logging in…" : "Log in"}</button>
        </form>
      </main>
    );
  }

  const badge = (n: number | null) => (n === null ? null : <span className="adm-count">{n >= 100 ? "100+" : n}</span>);

  return (
    <main className="container section first">
      <div className="page-head">
        <div className="eyebrow">Admin</div>
        <h1>Curation desk.</h1>
        <p className="lede">Review submissions, classify contracts and manage API keys. Nothing here is public until the next discovery run promotes it.</p>
      </div>

      <div className="adm-tabs" role="tablist" aria-label="Admin sections">
        {([
          ["submissions", "Submissions", counts.submissions],
          ["discovered", "Discovered", counts.discovered],
          ["classify", "Classify", null],
          ["keys", "API keys", counts.keys],
        ] as [Tab, string, number | null][]).map(([id, label, n]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}{badge(n)}</button>
        ))}
      </div>

      <div className="adm-body">
        {tab === "submissions" && <SubmissionsPanel categories={categories} onExpired={expired} onCount={onSubCount} />}
        {tab === "discovered" && (
          <DiscoveredPanel onExpired={expired} onCount={onDiscCount}
            onClassify={(address, name) => { setPrefill({ address, name, nonce: Date.now() }); setTab("classify"); }} />
        )}
        {tab === "classify" && <ClassifyPanel categories={categories} prefill={prefill} onExpired={expired} onSaved={() => setPrefill(null)} />}
        {tab === "keys" && <KeysPanel onExpired={expired} onCount={onKeyCount} />}
      </div>
    </main>
  );
}
