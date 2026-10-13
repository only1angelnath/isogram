import type { Metadata } from "next";
import { getApiBaseUrlForBadge } from "@/lib/api";
import { CodeBlock } from "@/components/CodeBlock";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Badges", description: "Embed a project's Arc Native Score in a README or website." };

export default function BadgesPage() {
  let base = "https://isogramapi.onrender.com";
  try { base = getApiBaseUrlForBadge(); } catch { /* keep the default */ }
  const url = `${base}/badge/YOUR-PROJECT-ID.svg`;
  return (
    <>
      <div className="page-head">
        <div className="eyebrow">Documentation</div>
        <h1>Badges.</h1>
        <p className="lede">A small SVG that shows a project&apos;s current Arc Native Score. It is served by the API, so it always matches the dashboard.</p>
      </div>
      <div className="prose">
        <h2 id="embed">Embed it</h2>
        <p>Find your project&apos;s id in its page address (<code>/projects/<b>your-project-id</b></code>) or search by contract on the dashboard. Then paste one of these.</p>
        <CodeBlock label="Markdown (README)" code={`[![Arc Native Score](${url})](https://isogram.vercel.app/projects/YOUR-PROJECT-ID)`} />
        <CodeBlock label="HTML" code={`<a href="https://isogram.vercel.app/projects/YOUR-PROJECT-ID"><img src="${url}" alt="Arc Native Score" height="20"></a>`} />

        <h2 id="states">What it can say</h2>
        <div className="tbl">
          <table>
            <thead><tr><th>Badge shows</th><th>Meaning</th></tr></thead>
            <tbody>
              <tr><td>A score such as <code>0.62</code></td><td>A DeFi protocol with a computed score, relative to other DeFi protocols on Arc.</td></tr>
              <tr><td><code>insufficient data</code></td><td>A DeFi protocol that is tracked but does not have enough activity yet.</td></tr>
              <tr><td><code>not scored</code></td><td>Tokens, stablecoins, launchpads and infrastructure are not scored (they have no TVL to compare). This is not a bad grade.</td></tr>
            </tbody>
          </table>
        </div>
        <p>An unknown project id returns 404, so a typo shows as a broken image rather than a made-up score.</p>

        <h2 id="caching">Caching and limits</h2>
        <ul>
          <li>Badges are cached for one hour (<code>Cache-Control: max-age=3600</code>), and the score itself refreshes every four hours.</li>
          <li>Badge requests have their own limit of 300 per minute per address, separate from the API limits, so README images are not throttled.</li>
          <li>No API key is needed.</li>
        </ul>
      </div>
    </>
  );
}
