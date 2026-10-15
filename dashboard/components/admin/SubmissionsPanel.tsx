"use client";

// SubmissionsPanel.tsx - the review queue. Pending submissions show everything the submitter sent,
// and approving needs a category from the real taxonomy (the public form's labels are only hints).

import { useCallback, useEffect, useState } from "react";
import {
  CategoryRow, SessionExpiredError, Submission, adminFetch, errorText, safeHttpUrl, suggestCategory, timeAgo, xUrl,
} from "@/components/admin/adminApi";
import { Addr, CategorySelect, Consequence, TrackedBadge } from "@/components/admin/ui";

type View = "pending" | "approved" | "rejected";
interface PanelProps { categories: CategoryRow[]; onExpired: () => void; onCount: (n: number) => void }

function Details({ s }: { s: Submission }) {
  const site = safeHttpUrl(s.socials?.website);
  const x = xUrl(s.socials?.x);
  return (
    <dl className="adm-dl">
      <div><dt>Submitter says</dt><dd>{s.proposed_category || "—"}</dd></div>
      <div><dt>Website</dt><dd>{site ? <a href={site} target="_blank" rel="noreferrer noopener">{site.replace(/^https:\/\//, "").replace(/\/$/, "")} ↗</a> : (s.socials?.website ? <span className="iso-dim">{s.socials.website} (not https, not linked)</span> : "—")}</dd></div>
      <div><dt>X</dt><dd>{x ? <a href={x} target="_blank" rel="noreferrer noopener">{s.socials?.x} ↗</a> : (s.socials?.x || "—")}</dd></div>
      <div><dt>Contact</dt><dd>{s.submitter_contact || "—"}</dd></div>
      {s.note && <div className="wide"><dt>Note</dt><dd>{s.note}</dd></div>}
    </dl>
  );
}

function PendingCard({ s, categories, onDone, onExpired }: {
  s: Submission; categories: CategoryRow[]; onDone: (msg: string) => void; onExpired: () => void;
}) {
  const [category, setCategory] = useState(() => suggestCategory(s.proposed_category, categories));
  const [name, setName] = useState(s.proposed_name ?? "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  // The categories arrive after the first render on a fresh page load.
  useEffect(() => { setCategory((c) => c || suggestCategory(s.proposed_category, categories)); }, [categories, s.proposed_category]);

  async function decide(decision: "approve" | "reject") {
    if (decision === "reject" && !window.confirm("Reject this submission? It leaves the queue.")) return;
    setBusy(decision);
    setError(null);
    try {
      await adminFetch(`submissions/${s.id}/review`, {
        method: "POST",
        body: JSON.stringify({ decision, category: decision === "approve" ? category : null, name: name.trim() || null, note: note.trim() || null }),
      });
      onDone(decision === "approve"
        ? `Approved ${name.trim() || s.contract_address}. It becomes a project on the next discovery run.`
        : "Rejected.");
    } catch (e) {
      if (e instanceof SessionExpiredError) onExpired();
      else setError(errorText(e, "Could not save the decision."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className="panel adm-card">
      <header className="adm-card-head">
        <div>
          <h3>{s.proposed_name || "Unnamed submission"}</h3>
          <Addr address={s.contract_address} />
        </div>
        <span className="adm-time" title={s.created_at}>{timeAgo(s.created_at)}</span>
      </header>
      <TrackedBadge address={s.contract_address} />
      <Details s={s} />
      <div className="adm-form">
        <div className="adm-field">
          <label htmlFor={`cat-${s.id}`}>Category</label>
          <CategorySelect id={`cat-${s.id}`} value={category} onChange={setCategory} categories={categories} />
          {!category && <p className="adm-hint">The submitter chose &ldquo;{s.proposed_category || "nothing"}&rdquo;, which is not a category. Pick one.</p>}
        </div>
        <div className="adm-field">
          <label htmlFor={`name-${s.id}`}>Project name</label>
          <input id={`name-${s.id}`} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="adm-field wide">
          <label htmlFor={`note-${s.id}`}>Reviewer note (kept for the record, not shown publicly)</label>
          <input id={`note-${s.id}`} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="Why approved or rejected" />
        </div>
      </div>
      <Consequence category={category} categories={categories} />
      {error && <p className="kf-error" role="alert">{error}</p>}
      <div className="adm-actions">
        <button type="button" className="btn" disabled={!category || busy !== null} onClick={() => decide("approve")}>{busy === "approve" ? "Approving…" : "Approve"}</button>
        <button type="button" className="btn-ghost adm-ghost" disabled={busy !== null} onClick={() => decide("reject")}>{busy === "reject" ? "Rejecting…" : "Reject"}</button>
      </div>
    </article>
  );
}

export function SubmissionsPanel({ categories, onExpired, onCount }: PanelProps) {
  const [view, setView] = useState<View>("pending");
  const [rows, setRows] = useState<Submission[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await adminFetch<Submission[]>(`submissions?status=${view}&limit=100`);
      setRows(data);
      setError(null);
      if (view === "pending") onCount(data.length);
    } catch (e) {
      if (e instanceof SessionExpiredError) onExpired();
      else setError(errorText(e, "Could not load submissions."));
    }
  }, [view, onExpired, onCount]);

  useEffect(() => { setRows(null); load(); }, [load]);

  return (
    <section aria-labelledby="sub-h">
      <div className="adm-bar">
        <h2 id="sub-h">Submissions</h2>
        <div className="adm-seg" role="group" aria-label="Show">
          {(["pending", "approved", "rejected"] as View[]).map((v) => (
            <button key={v} type="button" aria-pressed={view === v} onClick={() => { setView(v); setMessage(null); }}>{v}</button>
          ))}
        </div>
      </div>
      {message && <p className="adm-ok" role="status">{message}</p>}
      {error && <p className="kf-error" role="alert">{error}</p>}
      {rows === null && !error && <p className="iso-dim">Loading…</p>}
      {rows?.length === 0 && <p className="iso-dim">{view === "pending" ? "Nothing waiting. New submissions from /submit appear here." : `No ${view} submissions yet.`}</p>}
      <div className="adm-list">
        {rows?.map((s) =>
          view === "pending" ? (
            <PendingCard key={s.id} s={s} categories={categories} onExpired={onExpired}
              onDone={(msg) => { setMessage(msg); load(); }} />
          ) : (
            <article key={s.id} className="panel adm-card compact">
              <header className="adm-card-head">
                <div>
                  <h3>{s.proposed_name || "Unnamed submission"} <span className={`adm-chip ${s.status === "approved" ? "good" : "bad"}`}>{s.status}</span></h3>
                  <Addr address={s.contract_address} />
                </div>
                <span className="adm-time" title={s.reviewed_at ?? ""}>{timeAgo(s.reviewed_at)}</span>
              </header>
              {s.reviewer_note && <p className="adm-note">Note: {s.reviewer_note}</p>}
            </article>
          ),
        )}
      </div>
    </section>
  );
}
