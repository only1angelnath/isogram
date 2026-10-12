import type { Metadata } from "next";

export const metadata: Metadata = { title: "Methodology" };

const SECTIONS = [
  ["network", "Network metrics"],
  ["projects", "Projects"],
  ["defi", "TVL and score"],
  ["market", "Token market data"],
  ["venues", "DEX volume"],
  ["freshness", "Freshness"],
] as const;

export default function MethodologyPage() {
  return (
    <main className="container section first">
      <div className="page-head">
        <div className="eyebrow">Methodology</div>
        <h1>How the numbers are made.</h1>
        <p className="lede">
          Activity figures are read directly from Arc mainnet. Token prices and DEX volume come from a third party and are labelled
          wherever they appear. Missing data is shown as a dash, never as zero.
        </p>
        <nav className="toc" aria-label="Sections">
          {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}
        </nav>
      </div>

      <div className="prose">
        <h2 id="network">Network metrics</h2>
        <p>Ingestion follows the chain tip, reading each block&apos;s receipts, and keeps one rollup per UTC day. No per-transaction rows are stored.</p>
        <ul>
          <li><b>USDC gas</b> is gas actually paid (gas used × effective gas price) in the 6-decimal USDC view. Failed transactions still pay gas.</li>
          <li><b>USDC movement</b> is gross: every explicit USDC transfer, native sends and ERC-20 transfers counted once, including hops through routers. It is not economic volume. Mints and burns are excluded.</li>
          <li><b>Active addresses</b> are distinct transaction senders in a day.</li>
          <li><b>USDC decimals.</b> USDC is Arc&apos;s native gas asset, 18 decimals natively and 6 as an ERC-20. They are the same funds; every stored amount uses the 6-decimal view.</li>
          <li><b>Partial and early days.</b> Hatched bars are days still accruing. Days before the rollup pipeline existed have no failure, deployment or block counts, so those are blank.</li>
        </ul>

        <h2 id="projects">Projects</h2>
        <p>Contracts with meaningful activity are discovered automatically and classified (DeFi, launchpad, infrastructure, stablecoin, token). Names come from public on-chain metadata, so they can be misleading; <b>verified</b> marks hand-checked projects and nothing else is an endorsement.</p>
        <ul>
          <li>Each type is measured with the metrics that fit it: TVL and score for DeFi, price for tokens, usage for infrastructure.</li>
          <li>Launchpads are a curated list of platforms. Tokens launched through them are listed under Tokens.</li>
          <li><b>Holders</b> come from Arc&apos;s explorer, refreshed about every 12 hours. A dash means the explorer does not index the address as a token.</li>
          <li><b>Links</b> are validated (https only, rebuilt on each platform&apos;s own host). Links on discovered tokens are registered by the deployer and are unverified.</li>
          <li>Project owners can propose a contract for listing; submissions go to a human review queue.</li>
        </ul>

        <h2 id="defi">TVL and Arc Native Score</h2>
        <p>Only DeFi protocols have TVL and a score. TVL is the live on-chain balance of the protocol&apos;s contracts. The score combines gas, users, TVL and contract age, normalised against other DeFi protocols only, so it is a ranking within a small peer group and not an absolute quality measure. Other types show a dash.</p>

        <h2 id="market">Token market data</h2>
        <p>Price, 24h change, volume, liquidity and FDV come from GeckoTerminal (CoinGecko) for token, stablecoin and launchpad projects, refreshed hourly. Only about half of tracked tokens have a priced pool, and most are thin. Names are chosen by deployers: a token called &ldquo;Bitcoin&rdquo; is not necessarily Bitcoin.</p>
        <table>
          <thead><tr><th>Flag</th><th>Meaning</th></tr></thead>
          <tbody>
            <tr><td><code>thin</code></td><td>Under $10,000 of liquidity. The price is easy to move; FDV is hidden.</td></tr>
            <tr><td><code>no trading</code></td><td>Liquidity, but under 1% of it traded in 24h. The price may be stale; FDV is hidden.</td></tr>
            <tr><td>CoinGecko tag</td><td>The token maps to a CoinGecko listing. Without it, the price comes from a DEX pool and is unverified.</td></tr>
          </tbody>
        </table>
        <ul>
          <li>24h volume covers all pools. 7d volume covers only the most liquid pool, so it can understate multi-pool tokens.</li>
          <li>24h change is the top pool&apos;s change, shown only when the token is that pool&apos;s base token.</li>
          <li>Market data older than 24 hours is hidden.</li>
        </ul>

        <h2 id="venues">DEX volume</h2>
        <p>Each venue&apos;s busiest pools are read from GeckoTerminal every hour and summed. Uniswap V2, V3 and V4 stay separate, as GeckoTerminal and CoinGecko list them.</p>
        <ul>
          <li><b>Anomaly filter.</b> Raw sums are not trustworthy on Arc: one venue summed to $21.7M against $0.4M on CoinGecko because a few pools reported huge volume from two or three wallets. Pools with fewer than 10 traders in 24 hours, or volume above 25× their reserves, are left out and the excluded amount is shown beside each venue.</li>
          <li>CoinGecko&apos;s own filter is not public, so totals can differ from theirs.</li>
          <li>A leading &ldquo;≥&rdquo; means the venue has more pools than the scan covers.</li>
          <li>Venues are listed as DEXes unless confirmed as launch platforms.</li>
        </ul>

        <h2 id="freshness">Freshness</h2>
        <p>The status pill reads the API&apos;s <code>/metrics/status</code>: the timestamp of the last block applied and how far behind now that is. It says live only when that lag is under ten minutes. Scores refresh every four hours. This is research data, not financial advice.</p>
      </div>
    </main>
  );
}
