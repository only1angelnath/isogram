import type { Metadata } from "next";
import { getApiBaseUrlForBadge } from "@/lib/api";
import { CodeBlock } from "@/components/CodeBlock";
import { KeyForm } from "@/components/KeyForm";
import { Endpoint, GROUPS, RATE_LIMITS } from "@/lib/apiDocs";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "API reference", description: "The Isogram REST API: endpoints, rate limits, API keys and conventions." };

function curlFor(e: Endpoint, base: string, withKey: boolean): string {
  if (e.curl) return e.curl.replaceAll("{base}", base);
  return `curl ${withKey ? `-H "X-API-Key: $ISOGRAM_API_KEY" ` : ""}"${base}${e.call}"`;
}

function EndpointBlock({ e, base }: { e: Endpoint; base: string }) {
  return (
    <section className="ep" id={e.id}>
      <h3><span className={`m ${e.method.toLowerCase()}`}>{e.method}</span><code>{e.path}</code></h3>
      <p className="sum">{e.summary}</p>
      {e.notes && <ul className="notes">{e.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      {e.params && (
        <div className="tbl">
          <table>
            <thead><tr><th>Parameter</th><th>In</th><th>Type</th><th>Description</th></tr></thead>
            <tbody>
              {e.params.map((p) => (
                <tr key={p.name}>
                  <td><code>{p.name}</code>{p.required && <span className="iso-dim"> *</span>}</td>
                  <td>{p.in}</td>
                  <td>{p.type}</td>
                  <td>{p.desc}{p.default && <span className="iso-dim"> Default {p.default}.</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <CodeBlock code={curlFor(e, base, false)} />
      <details>
        <summary>Example response (shape exact, values illustrative)</summary>
        <CodeBlock code={e.response} />
      </details>
    </section>
  );
}

export default function ApiReferencePage() {
  let base = "https://isogramapi.onrender.com";
  try { base = getApiBaseUrlForBadge(); } catch { /* keep the default */ }

  return (
    <>
      <div className="page-head">
        <div className="eyebrow">Documentation</div>
        <h1>API reference.</h1>
        <p className="lede">
          A read-only REST API over everything the dashboard shows. JSON over HTTPS, open CORS, no key needed to start.
          The dashboard itself is a client of this API.
        </p>
        <nav className="api-toc" aria-label="On this page">
          <a href="#quickstart">Quickstart</a>
          <a href="#keys">API keys</a>
          <a href="#limits">Rate limits</a>
          <a href="#conventions">Conventions</a>
          <a href="#errors">Errors</a>
          {GROUPS.map((g) => <a key={g.id} href={`#g-${g.id}`}>{g.title}</a>)}
        </nav>
      </div>

      <div className="prose">
        <h2 id="quickstart">Quickstart</h2>
        <p>Base URL:</p>
        <CodeBlock code={base} />
        <p>Is the data fresh, then what is on Arc:</p>
        <CodeBlock code={`curl ${base}/metrics/status\ncurl "${base}/metrics/network/daily?days=7"\ncurl "${base}/projects"`} />
        <p>
          The same in JavaScript, reading the rate-limit headers (browsers can read them; CORS exposes them):
        </p>
        <CodeBlock code={`const res = await fetch("${base}/metrics/network/daily?days=7", {\n  headers: { "X-API-Key": process.env.ISOGRAM_API_KEY }, // optional\n});\nif (res.status === 429) {\n  const wait = Number(res.headers.get("Retry-After")); // seconds\n}\nconsole.log(res.headers.get("X-RateLimit-Remaining"), await res.json());`} />
        <p>A browser-friendly, interactive reference generated from the code is also available as <a href={`${base}/docs`} target="_blank" rel="noreferrer">Swagger UI</a>.</p>

        <h2 id="keys">API keys</h2>
        <p>
          You do not need a key to call the API, but a free key raises your limit tenfold and keeps your traffic separate from everyone else
          sharing your network address. Send it as the <code>X-API-Key</code> header.
        </p>
        <KeyForm apiBase={base} />
        <ul>
          <li>The key is shown once. Only a hash is stored, so a lost key cannot be recovered; create another.</li>
          <li>Treat it like a password: keep it on your server, not in front-end code or a public repo. If it leaks, create a new one and ask for the old one (identified by its first 8 characters) to be revoked.</li>
          <li>A wrong or revoked key gets <code>401</code>, never a silent downgrade, so typos are noticed. Revocation takes effect within a minute.</li>
          <li>Up to 5 new keys per address per day and 3 active keys per email. Need more than 600 a minute? Open an issue on GitHub with what you are building.</li>
          <li><b>Your email.</b> It is required so we can contact you about the API: changes, limits and abuse. It is not verified, never shown publicly, never returned by the API, and not sold or shared. To have it deleted along with your key, ask on GitHub.</li>
        </ul>

        <h2 id="limits">Rate limits</h2>
        <div className="tbl">
          <table>
            <thead><tr><th>Tier</th><th>Limit</th><th>Counted per</th><th>How</th></tr></thead>
            <tbody>{RATE_LIMITS.map((r) => <tr key={r.id}><td>{r.tier}</td><td>{r.limit}</td><td>{r.scope}</td><td>{r.how}</td></tr>)}</tbody>
          </table>
        </div>
        <p>Limits use a sliding one-minute window. <code>/health</code> and <code>/</code> are never limited. Every response carries:</p>
        <div className="tbl">
          <table>
            <thead><tr><th>Header</th><th>Meaning</th></tr></thead>
            <tbody>
              <tr><td><code>X-RateLimit-Limit</code></td><td>Requests allowed per minute for your tier.</td></tr>
              <tr><td><code>X-RateLimit-Remaining</code></td><td>Requests left in the current window.</td></tr>
              <tr><td><code>X-RateLimit-Tier</code></td><td><code>anonymous</code>, <code>registered</code> or <code>badge</code>.</td></tr>
              <tr><td><code>Retry-After</code></td><td>On a <code>429</code> only: seconds until you can retry.</td></tr>
            </tbody>
          </table>
        </div>
        <div className="callout"><b>Be kind to the free tier.</b> Responses change at most every few minutes (scores every four hours), so caching for a minute or more loses you nothing. On a <code>429</code>, wait <code>Retry-After</code> seconds instead of retrying immediately.</div>

        <h2 id="conventions">Conventions</h2>
        <ul>
          <li><b>null means not measured, never 0.</b> A field is <code>null</code> when it does not apply (a token has no TVL) or was not recorded. Handle it explicitly.</li>
          <li><b>Days are UTC calendar days</b>, written <code>YYYY-MM-DD</code>, oldest first. The latest day is usually partial (<code>partial: true</code>). Days the pipeline did not cover are absent, not zero-filled.</li>
          <li><b>USDC amounts are in USDC</b> (the 6-decimal view), as plain numbers. USDC is Arc&apos;s native gas asset; the 18-decimal native view and the 6-decimal ERC-20 view are the same funds and are never added together.</li>
          <li><b>Ratios are fractions</b> (<code>failed_rate: 0.012</code> is 1.2%) except fields named <code>_pct</code>, which are percent.</li>
          <li><b>Timestamps</b> are ISO 8601 in UTC.</li>
          <li><b>Third-party data</b> (<code>market</code>, venues) carries <code>source</code> and <code>fetched_at</code>, and is treated as absent once stale.</li>
          <li><b>Stability.</b> The API is pre-1.0 (version 0.3). New fields may be added; an existing field will not change meaning without a note in the repository changelog.</li>
          <li><b>CORS</b> is open (<code>*</code>) for GET and POST, without credentials, so you can call it from a browser. Prefer a server-side call when you use a key.</li>
        </ul>

        <h2 id="errors">Errors</h2>
        <div className="tbl">
          <table>
            <thead><tr><th>Status</th><th>When</th></tr></thead>
            <tbody>
              <tr><td><code>400</code></td><td>A malformed value, such as an address that is not 0x plus 40 hex characters, or an untracked token.</td></tr>
              <tr><td><code>401</code></td><td>The <code>X-API-Key</code> is invalid or revoked.</td></tr>
              <tr><td><code>404</code></td><td>No tracked project or contract with that id or address.</td></tr>
              <tr><td><code>422</code></td><td>A parameter is out of range (for example <code>days=500</code>) or a request body is invalid.</td></tr>
              <tr><td><code>429</code></td><td>Rate limit exceeded. Read <code>Retry-After</code>.</td></tr>
              <tr><td><code>503</code></td><td>A data source is temporarily unavailable. The API says so rather than returning an empty list that would look like no activity.</td></tr>
            </tbody>
          </table>
        </div>
        <CodeBlock label="Error body" code={`{ "detail": "No tracked project 'nope'" }`} />
        <p>The free hosting tier can take 5 to 20 seconds to wake after a quiet period. Retry once if your first request times out.</p>
      </div>

      <div className="prose">
        {GROUPS.map((g) => (
          <div key={g.id}>
            <div className="group-head"><h2 id={`g-${g.id}`}>{g.title}</h2><p>{g.blurb}</p></div>
            {g.endpoints.map((e) => <EndpointBlock key={e.id} e={e} base={base} />)}
          </div>
        ))}
      </div>
    </>
  );
}
