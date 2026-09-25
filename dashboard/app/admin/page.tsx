// app/admin/page.tsx — client component: password gate, then the
// submission review queue + manual classify form, all via
// /api/admin-proxy (never calling FastAPI's /admin/* directly from the
// browser — see that route's comment on why).
"use client";

import { useEffect, useState } from "react";

type Submission = {
  id: number;
  contract_address: string;
  proposed_name: string | null;
  proposed_category: string | null;
  socials: Record<string, string>;
  submitter_contact: string | null;
  note: string | null;
  status: string;
  created_at: string;
};

type DiscoveredContract = {
  contract_address: string;
  call_count: number;
  category: string | null;
  gecko_name: string | null;
  status: string;
  first_seen: string;
  last_seen: string;
};

async function proxy<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/admin-proxy/${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (res.status === 401) {
    throw new Error("SESSION_EXPIRED");
  }
  const body = await res.json();
  if (!res.ok) {
    throw new Error(body.detail || body.error || `Request failed (${res.status})`);
  }
  return body as T;
}

export default function AdminPage() {
  const [authed, setAuthed] = useState(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loggingIn, setLoggingIn] = useState(false);

  const [submissions, setSubmissions] = useState<Submission[] | null>(null);
  const [unclassified, setUnclassified] = useState<DiscoveredContract[] | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [classifyAddress, setClassifyAddress] = useState("");
  const [classifyCategory, setClassifyCategory] = useState("");
  const [classifyName, setClassifyName] = useState("");

  function handleSessionExpired() {
    setAuthed(false);
    setLoginError("Session expired — please log in again.");
  }

  async function loadAll() {
    try {
      const [subs, disc] = await Promise.all([
        proxy<Submission[]>("submissions"),
        proxy<DiscoveredContract[]>("discovered?status=unclassified&limit=30"),
      ]);
      setSubmissions(subs);
      setUnclassified(disc);
      setActionError(null);
    } catch (err) {
      if (err instanceof Error && err.message === "SESSION_EXPIRED") {
        handleSessionExpired();
      } else {
        setActionError(err instanceof Error ? err.message : "Failed to load");
      }
    }
  }

  useEffect(() => {
    if (authed) {
      loadAll();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authed]);

  async function handleLogin(e: React.FormEvent) {
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

  async function handleReview(id: number, decision: "approve" | "reject") {
    setBusyId(`sub-${id}`);
    setActionError(null);
    try {
      await proxy(`submissions/${id}/review`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      await loadAll();
    } catch (err) {
      if (err instanceof Error && err.message === "SESSION_EXPIRED") {
        handleSessionExpired();
      } else {
        setActionError(err instanceof Error ? err.message : "Review failed");
      }
    } finally {
      setBusyId(null);
    }
  }

  async function handleClassify(e: React.FormEvent) {
    e.preventDefault();
    setBusyId("classify-form");
    setActionError(null);
    try {
      await proxy("classify", {
        method: "POST",
        body: JSON.stringify({
          contract_address: classifyAddress,
          category: classifyCategory,
          name: classifyName || null,
        }),
      });
      setClassifyAddress("");
      setClassifyCategory("");
      setClassifyName("");
      await loadAll();
    } catch (err) {
      if (err instanceof Error && err.message === "SESSION_EXPIRED") {
        handleSessionExpired();
      } else {
        setActionError(err instanceof Error ? err.message : "Classify failed");
      }
    } finally {
      setBusyId(null);
    }
  }

  if (!authed) {
    return (
      <main style={{ maxWidth: 360, margin: "4rem auto", padding: "0 1rem" }}>
        <h1>Isogram Admin</h1>
        <form onSubmit={handleLogin}>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Admin password"
            autoFocus
            style={{ width: "100%", padding: "0.5rem", marginBottom: "0.5rem" }}
          />
          <button type="submit" disabled={loggingIn} style={{ width: "100%", padding: "0.5rem" }}>
            {loggingIn ? "Logging in…" : "Log in"}
          </button>
        </form>
        {loginError && <p style={{ color: "#FF5B2E" }}>{loginError}</p>}
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <h1>Isogram Admin</h1>
      {actionError && <p style={{ color: "#FF5B2E" }}>{actionError}</p>}

      <section style={{ marginTop: "2rem" }}>
        <h2>Pending submissions ({submissions?.length ?? "…"})</h2>
        {submissions?.length === 0 && <p>Nothing pending.</p>}
        {submissions?.map((s) => (
          <div key={s.id} style={{ border: "1px solid #333", padding: "1rem", marginBottom: "0.5rem" }}>
            <div><strong>{s.proposed_name || s.contract_address}</strong></div>
            <div style={{ fontFamily: "monospace", fontSize: "0.85em" }}>{s.contract_address}</div>
            <div>Proposed category: {s.proposed_category || "—"}</div>
            {s.note && <div>Note: {s.note}</div>}
            {s.submitter_contact && <div>Contact: {s.submitter_contact}</div>}
            <div style={{ marginTop: "0.5rem" }}>
              <button
                disabled={busyId === `sub-${s.id}`}
                onClick={() => handleReview(s.id, "approve")}
                style={{ marginRight: "0.5rem" }}
              >
                Approve
              </button>
              <button disabled={busyId === `sub-${s.id}`} onClick={() => handleReview(s.id, "reject")}>
                Reject
              </button>
            </div>
          </div>
        ))}
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Unclassified, high call-count contracts</h2>
        {unclassified?.length === 0 && <p>None right now.</p>}
        {unclassified?.map((c) => (
          <div key={c.contract_address} style={{ fontFamily: "monospace", fontSize: "0.9em" }}>
            {c.contract_address} — {c.call_count} calls — last seen {c.last_seen}
          </div>
        ))}
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Manual classify</h2>
        <form onSubmit={handleClassify}>
          <input
            placeholder="0x contract address"
            value={classifyAddress}
            onChange={(e) => setClassifyAddress(e.target.value)}
            style={{ display: "block", width: "100%", padding: "0.5rem", marginBottom: "0.5rem" }}
          />
          <input
            placeholder="category (e.g. dex, token, infra)"
            value={classifyCategory}
            onChange={(e) => setClassifyCategory(e.target.value)}
            style={{ display: "block", width: "100%", padding: "0.5rem", marginBottom: "0.5rem" }}
          />
          <input
            placeholder="name (optional)"
            value={classifyName}
            onChange={(e) => setClassifyName(e.target.value)}
            style={{ display: "block", width: "100%", padding: "0.5rem", marginBottom: "0.5rem" }}
          />
          <button type="submit" disabled={busyId === "classify-form"}>
            {busyId === "classify-form" ? "Saving…" : "Classify"}
          </button>
        </form>
        <p style={{ fontSize: "0.85em", opacity: 0.7 }}>
          Promotes to a tracked project on the next scheduled discovery run, not immediately.
        </p>
      </section>
    </main>
  );
}
