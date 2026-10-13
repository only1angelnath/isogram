"use client";

import { useState } from "react";

/** A code sample with a copy button. Plain text only (no highlighting), so nothing to sanitise. */
export function CodeBlock({ code, label }: { code: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text is still selectable */
    }
  }
  return (
    <div className="code">
      {label && <div className="code-label">{label}</div>}
      <button type="button" className="code-copy" onClick={copy} aria-label="Copy to clipboard">{copied ? "Copied" : "Copy"}</button>
      <pre tabIndex={0}><code>{code}</code></pre>
    </div>
  );
}
