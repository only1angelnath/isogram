import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Documentation",
  description: "What Isogram is, where its numbers come from, and how to use them.",
};

export default function DocsOverview() {
  return (
    <>
      <div className="page-head">
        <div className="eyebrow">Documentation</div>
        <h1>The data truth layer for Arc.</h1>
        <p className="lede">
          Isogram reads Arc mainnet directly and turns it into network activity, project metrics, token and DEX data and DeFi scores,
          through a dashboard, a public API and an embeddable badge. Every number says where it came from; every gap is shown as a gap.
        </p>
      </div>

      <div className="prose">
        <h2 id="why">Why it exists</h2>
        <p>
          Arc mainnet launched on 16 September 2026 with USDC as its native gas asset and no public place to answer simple questions:
          what is deployed, what is being used, how much USDC gas is being spent and where, and which projects are alive.
          Isogram is that place. It is built for three kinds of reader:
        </p>
        <ul>
          <li><b>Builders</b> who want to see their own contracts and their peers, and embed a badge in a README.</li>
          <li><b>The Arc ecosystem team and reviewers</b> who want a fast read on chain health.</li>
          <li><b>Anyone curious</b> who wants a clear, open way to browse a brand-new chain.</li>
        </ul>

        <h2 id="how">How it works</h2>
        <div className="flow" role="list">
          <div role="listitem"><b>Arc mainnet</b><span>Public RPC, chain ID 5042</span></div>
          <div role="listitem"><b>Ingestion</b><span>Follows the tip, one receipts call per block</span></div>
          <div role="listitem"><b>Daily rollups</b><span>Postgres, one row per metric per UTC day</span></div>
          <div role="listitem"><b>API</b><span>Read-only, rate limited, open CORS</span></div>
          <div role="listitem"><b>Dashboard, badge, your app</b><span>All clients of the same API</span></div>
        </div>
        <p>
          Isogram follows Arc mainnet block by block and keeps one summary row per metric per UTC day, never
          individual transactions. Those daily numbers are combined with live contract balances to produce TVL and
          the Arc Native Score, and with third-party market data where it exists. One read-only API serves all of it.
          The dashboard and the badge are ordinary clients of that API, and so can you be.
        </p>

        <h2 id="sources">Where the numbers come from</h2>
        <div className="tbl">
          <table>
            <thead><tr><th>Data</th><th>Source</th><th>Refresh</th></tr></thead>
            <tbody>
              <tr><td>Transactions, failures, USDC gas, deployments, active addresses, USDC movement, per-project usage</td><td>Arc mainnet RPC, directly</td><td>Continuous (seconds behind the tip)</td></tr>
              <tr><td>TVL</td><td>Live token balances of DeFi contracts, read on-chain</td><td>Every 4 hours</td></tr>
              <tr><td>Arc Native Score</td><td>Computed by Isogram from the above</td><td>Every 4 hours</td></tr>
              <tr><td>Token price, volume, liquidity, FDV</td><td>GeckoTerminal (CoinGecko), third party</td><td>Hourly</td></tr>
              <tr><td>DEX and launch venue volume</td><td>GeckoTerminal, third party</td><td>Hourly</td></tr>
              <tr><td>Holder counts</td><td>Arc explorer</td><td>About every 12 hours</td></tr>
              <tr><td>Website and social links</td><td>Hand-set for verified projects; token deployers&apos; self-reported links otherwise</td><td>Weekly</td></tr>
            </tbody>
          </table>
        </div>
        <p>Third-party figures are labelled as such wherever they appear on the dashboard and in the API (<code>source</code>).</p>

        <h2 id="principles">Principles</h2>
        <ul>
          <li><b>Missing is not zero.</b> A figure that was not measured is a dash in the dashboard and <code>null</code> in the API.</li>
          <li><b>Partial is marked.</b> The current UTC day is hatched. Days the pipeline did not cover are left out, never filled in.</li>
          <li><b>Third party is labelled.</b> On-chain activity and market data have different trust levels and are never blended silently.</li>
          <li><b>Listed is not endorsed.</b> Projects are discovered automatically; only <i>verified</i> ones were checked by a person. Names are chosen by deployers and can be misleading.</li>
          <li><b>Research, not advice.</b> Nothing here is a trading signal or financial advice.</li>
        </ul>

        <h2 id="start">Where to go next</h2>
        <ul>
          <li><Link href="/docs/methodology">Methodology</Link>: exact definitions, the score formula, filters and known limits.</li>
          <li><Link href="/docs/api">API reference</Link>: every endpoint, rate limits and how to get a free key.</li>
          <li><Link href="/docs/badges">Badges</Link>: embed a project&apos;s score in a README.</li>
          <li><a href="https://github.com/only1angelnath/isogram" target="_blank" rel="noreferrer">Source code</a>: ingestion, scoring, API and dashboard, all open.</li>
        </ul>
      </div>
    </>
  );
}
