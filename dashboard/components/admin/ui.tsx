"use client";

// ui.tsx - small pieces shared by the admin panels.

import Link from "next/link";
import { useEffect, useState } from "react";
import { CategoryRow, EXPLORER, SEGMENT_LABEL, SEGMENT_NOTE, ADDRESS_RE, segmentOf, shortAddress } from "@/components/admin/adminApi";

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1400);
    } catch { /* clipboard blocked: the text is still selectable */ }
  }
  return <button type="button" className="adm-mini" onClick={copy}>{done ? "Copied" : label}</button>;
}

/** Shortened address with copy and explorer links; the full address is in the tooltip and the copy. */
export function Addr({ address }: { address: string }) {
  return (
    <span className="adm-addr">
      <code className="mono" title={address}>{shortAddress(address)}</code>
      <CopyButton text={address} />
      <a className="adm-mini" href={`${EXPLORER}${address}`} target="_blank" rel="noreferrer">Explorer ↗</a>
    </span>
  );
}

/** Says so when the address is already a tracked project. A courtesy check, silent on failure. */
export function TrackedBadge({ address }: { address: string }) {
  const [tracked, setTracked] = useState<{ id: string; name: string } | null>(null);
  useEffect(() => {
    setTracked(null);
    if (!ADDRESS_RE.test(address)) return;
    let cancelled = false;
    fetch(`/api/search?address=${address}`)
      .then((r) => (r.ok ? (r.json() as Promise<{ id: string; name: string }>) : null))
      .then((t) => { if (!cancelled && t && t.id) setTracked(t); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [address]);
  if (!tracked) return null;
  return <Link className="adm-chip good" href={`/projects/${encodeURIComponent(tracked.id)}`} target="_blank">Already tracked: {tracked.name}</Link>;
}

/** Dropdown of the API's real categories, grouped by what they mean for the project. */
export function CategorySelect({ id, value, onChange, categories, required }: {
  id: string; value: string; onChange: (v: string) => void; categories: CategoryRow[]; required?: boolean;
}) {
  const groups = new Map<string, CategoryRow[]>();
  for (const c of categories) groups.set(c.segment, [...(groups.get(c.segment) ?? []), c]);
  return (
    <select id={id} value={value} required={required} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose a category…</option>
      {[...groups.entries()].map(([seg, rows]) => (
        <optgroup key={seg} label={SEGMENT_LABEL[seg] ?? seg}>
          {rows.map((r) => <option key={r.category} value={r.category}>{r.category}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

/** One line on what the chosen category does to the project. */
export function Consequence({ category, categories }: { category: string; categories: CategoryRow[] }) {
  if (!category) return null;
  const seg = segmentOf(category, categories);
  if (!seg) return null;
  return <p className="adm-note"><b>{SEGMENT_LABEL[seg] ?? seg}.</b> {SEGMENT_NOTE[seg] ?? ""}</p>;
}
