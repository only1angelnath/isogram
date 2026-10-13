import type { Metadata } from "next";
import { CodeBlock } from "@/components/CodeBlock";

export const metadata: Metadata = {
  title: "Methodology",
  description: "Exact definitions behind every Isogram number: metrics, USDC handling, classification, TVL, the score, market data and known limits.",
};

const SECTIONS = [
  ["pipeline", "Pipeline"],
  ["network", "Network metrics"],
  ["usdc", "USDC"],
  ["projects", "Projects"],
  ["segments", "Segments"],
  ["tvl", "TVL"],
  ["score", "Score"],
  ["market", "Token market data"],
  ["venues", "DEX volume"],
  ["freshness", "Freshness"],
  ["limits", "Known limits"],
] as const;

export default function MethodologyPage() {
  return (
    <>
      <div className="page-head">
        <div className="eyebrow">Documentation</div>
        <h1>Methodology.</h1>
        <p className="lede">
          How every number is made, what it leaves out, and where it can mislead. Activity is read from the chain; market data is
          third-party and labelled; missing data is shown as missing.
        </p>
        <nav className="api-toc" aria-label="On this page">
          {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}
        </nav>
      </div>

      <div className="prose">
        <h2 id="pipeline">Pipeline</h2>
        <ol>
          <li><b>Read.</b> A worker follows Arc mainnet&apos;s tip over public RPC, fetching each block&apos;s receipts with <code>eth_getBlockReceipts</code> (two RPC calls per block). It rotates across several RPC endpoints with retry and backoff, because a single free endpoint throttled CI traffic during development.</li>
          <li><b>Aggregate.</b> Receipts are summed in memory into one rollup per UTC day: per network, per contract, per token, active senders and per-contract users. No per-transaction rows are stored; the free database tier cannot hold Arc&apos;s 1 to 2 million transactions a day.</li>
          <li><b>Commit atomically.</b> A batch of rollup changes and the new checkpoint are written in one database transaction (<code>apply_ingest_batch</code>). A crash cannot double-count or skip a block.</li>
          <li><b>Score.</b> Every four hours a job reads the rollups and live on-chain balances and writes TVL and score rows.</li>
          <li><b>Serve.</b> A read-only API is the only reader of the database. The dashboard, the badge and third-party apps all go through it.</li>
        </ol>
        <p>Because only rollups are kept, a metric can be recomputed only for days still in the rollups, and a definition change means re-ingesting from the chain. This has happened once: see <a href="#usdc">USDC</a>.</p>

        <h2 id="network">Network metrics</h2>
        <div className="tbl">
          <table>
            <thead><tr><th>Metric</th><th>Definition</th></tr></thead>
            <tbody>
              <tr><td>Transactions</td><td>Transactions included in blocks on that UTC day, taken from receipts.</td></tr>
              <tr><td>Failed rate</td><td>Failed transactions divided by transactions. A failed transaction still pays gas.</td></tr>
              <tr><td>USDC gas</td><td>Gas used times effective gas price, summed, in USDC (6-decimal view). Includes failed transactions.</td></tr>
              <tr><td>Gas per transaction</td><td>USDC gas divided by transactions.</td></tr>
              <tr><td>Contracts deployed</td><td>Contract creations that day.</td></tr>
              <tr><td>Active addresses</td><td>Distinct transaction senders that day.</td></tr>
              <tr><td>Blocks</td><td>Blocks applied that day.</td></tr>
              <tr><td>USDC movement</td><td>Gross USDC transferred; see below.</td></tr>
            </tbody>
          </table>
        </div>
        <p>
          <b>Partial days.</b> The current UTC day is still accruing and is hatched in charts. If ingestion is behind the tip, the newest
          days are also incomplete and the status pill says so. <b>Early days.</b> 27 and 28 September 2026 predate the rollup
          pipeline: their transaction and gas totals exist, but failure, deployment, block and active-address counts are blank, and are
          not zero.
        </p>

        <h2 id="usdc">USDC</h2>
        <p>
          USDC is Arc&apos;s native gas asset. It is exposed two ways: an 18-decimal native balance used for gas and <code>msg.value</code>,
          and a 6-decimal ERC-20 at <code>0x3600…0000</code>. These are <b>the same funds</b>, not two assets. Isogram never adds them, never
          treats a move between them as a swap, and stores every USDC amount in the 6-decimal view, converting exactly once at ingestion.
        </p>
        <p>
          Arc emits USDC <code>Transfer</code> logs from two places: a native system log (<code>0xffff…fffe</code>, 18 decimals, once per
          explicit USDC movement including plain native sends) and the ERC-20 contract (6 decimals, ERC-20 calls only). One ERC-20
          transfer emits both. Isogram counts USDC movement from the <b>system log only</b>. Measured on 200 live blocks, the ERC-20
          stream alone missed 74% of USDC volume, because many transfers are plain native sends.
        </p>
        <ul>
          <li>The figure is <b>gross movement</b>: every transfer log counts, including intermediate hops through routers and pools, so one swap can contribute several. It is not economic volume.</li>
          <li>Mints and burns (a transfer to or from the zero address) are excluded as supply changes.</li>
          <li>EURC and USYC are ERC-20 only and are counted from their own transfer logs, in their own units. Volumes of different tokens are never summed.</li>
        </ul>

        <h2 id="projects">Projects</h2>
        <h3>Discovery</h3>
        <p>
          Each run looks at which contracts received meaningful activity in the rollups. New ones are classified and, when the
          classification is confident, promoted to a tracked project. Classification uses GeckoTerminal and explorer metadata and, for
          anything ambiguous, manual review. Plain wallets (no bytecode) are rejected before any lookup is spent.
        </p>
        <h3>Trust</h3>
        <ul>
          <li><b>Verified</b> projects were seeded or checked by a person, with every contract confirmed on-chain. Their category and contracts are protected by a database trigger, so automated discovery cannot overwrite them.</li>
          <li><b>Discovered</b> projects were promoted automatically. Their names come from public metadata that the deployer chose, so they can be misleading. Listing is not endorsement.</li>
          <li>Tokens whose name or symbol impersonates a brand (including Circle) are never auto-promoted. The stablecoin category is applied only to hand-seeded tokens, never inferred from a name containing &ldquo;usd&rdquo;.</li>
          <li>A discovered contract can never claim the slug or the contracts of a seeded project.</li>
        </ul>
        <h3>Attribution</h3>
        <p>
          Gas and usage are attributed to a project through its list of contracts <b>at read time</b>, so a contract promoted later is
          attributed retroactively for days still in the rollups. Per-project unique users are recorded only for contracts that were
          tracked when the day was ingested, so a newly promoted project accrues users from its promotion forward. Per-contract daily
          rows with fewer than three transactions on a closed day are dropped; network totals stay exact, so per-contract sums never exceed them.
        </p>
        <h3>Holders and links</h3>
        <p>
          Holder counts come from Arc&apos;s explorer, refreshed about every 12 hours; a dash means the explorer does not index the address
          as a token, and a count older than 72 hours is treated as unknown. Links are validated (https only, no credentials or unusual
          ports, real DNS names, platform handles rebuilt on each platform&apos;s own host). Links set by Isogram are tinted; links registered
          by a token&apos;s deployer are shown as unverified and opened with <code>noopener nofollow ugc</code>.
        </p>
        <h3>Submissions</h3>
        <p>Project owners can propose a contract through the API. A submission never lists anything by itself: it waits in a queue for a person to review.</p>

        <h2 id="segments">Segments</h2>
        <p>
          Every project belongs to a segment derived from its category, and each segment shows only the metrics that mean something for it.
          A score or TVL for a memecoin would be noise, so non-DeFi segments show a dash there.
        </p>
        <div className="tbl">
          <table>
            <thead><tr><th>Segment</th><th>Categories</th><th>Measured with</th></tr></thead>
            <tbody>
              <tr><td>DeFi</td><td>dex, lending, yield, liquid-staking</td><td>TVL, Arc Native Score, usage, gas</td></tr>
              <tr><td>Launchpads</td><td>launch platforms (a curated list)</td><td>Usage, holders, price of the platform token</td></tr>
              <tr><td>Infrastructure</td><td>infra, bridge, oracle, governance</td><td>Usage, users, gas, failure rate</td></tr>
              <tr><td>Stablecoins</td><td>stablecoin, institutional</td><td>Price and market data, holders, usage</td></tr>
              <tr><td>Tokens</td><td>token, meme, wrapped</td><td>Price, 24h change, volume, liquidity, holders</td></tr>
              <tr><td>Other</td><td>no category yet</td><td>Usage only. A category is never guessed.</td></tr>
            </tbody>
          </table>
        </div>
        <p>Tokens launched through a launchpad are always filed as tokens; the launchpad row is the platform itself, not its clones.</p>

        <h2 id="tvl">TVL</h2>
        <p>
          TVL exists only for DeFi protocols. It is the <b>live on-chain balance</b> of the tracked tokens held by the protocol&apos;s
          contracts, read with <code>balanceOf</code> at scoring time, not reconstructed from history. USDC is counted once (see above).
          It is a snapshot every four hours, not an average, and covers the tracked tokens only.
        </p>

        <h2 id="score">Arc Native Score</h2>
        <p>
          A single number from 0 to 1 that ranks DeFi protocols against each other. Four inputs, equal weights, each scaled to 0 to 1
          across the DeFi peer group:
        </p>
        <CodeBlock code={`score = 0.25 * normalize(usdc_gas_7d)\n      + 0.25 * normalize(unique_users_7d)\n      + 0.25 * normalize(tvl_usd)\n      + 0.25 * contract_age_bonus`} />
        <ul>
          <li><b>normalize</b> is min-max within the DeFi segment only: the least active protocol gets 0 on that input and the most active gets 1.</li>
          <li><b>usdc_gas_7d</b> is USDC gas paid by the protocol&apos;s contracts over the last 7 UTC days (today partial).</li>
          <li><b>unique_users_7d</b> is distinct transaction senders that called the protocol&apos;s contracts in the window.</li>
          <li><b>contract_age_bonus</b> ramps linearly from 0 at deployment to 1 at 30 days.</li>
        </ul>
        <div className="callout">
          <b>Read it as a ranking, not a grade.</b> It is relative to a small peer group, so one outlier rescales everyone, and with a
          single protocol in the group the value degrades to &ldquo;insufficient data&rdquo; rather than a number. The weights are
          deliberately simple and explainable, and any change to the formula is recorded in a decision log before it ships. Scores from
          before 8 October 2026 used a different peer group and are not comparable.
        </div>

        <h2 id="market">Token market data</h2>
        <p>
          Price, 24h change, volume, liquidity and fully diluted value come from GeckoTerminal (CoinGecko&apos;s on-chain data) for token,
          stablecoin and launchpad projects, refreshed hourly. This is <b>third-party data</b>, not read from Arc by Isogram, and every
          surface says so. Roughly half of tracked tokens have a priced pool at all, and most of those are thin. A token&apos;s name is chosen
          by its deployer: one called &ldquo;Bitcoin&rdquo; was priced at $82,000 with $59 of daily volume.
        </p>
        <div className="tbl">
          <table>
            <thead><tr><th>Flag</th><th>Rule</th><th>Effect</th></tr></thead>
            <tbody>
              <tr><td><code>ok</code></td><td>At least $10,000 liquidity and 24h volume of at least 1% of it</td><td>Price, volume, FDV and market cap shown</td></tr>
              <tr><td><code>thin</code></td><td>Liquidity unknown or under $10,000</td><td>Price shown dimmed; FDV and market cap hidden</td></tr>
              <tr><td><code>inactive</code></td><td>$10,000+ liquidity but under 1% of it traded in 24h</td><td>Price may be stale; FDV and market cap hidden</td></tr>
            </tbody>
          </table>
        </div>
        <ul>
          <li>FDV is price times supply on Arc, not a global figure, and is withheld unless quality is <code>ok</code>, because it inherits every flaw of the price.</li>
          <li>The CoinGecko tag means GeckoTerminal maps the token to a CoinGecko listing. Without it the price comes from a DEX pool and is unverified.</li>
          <li>24h volume covers all pools. 7-day volume covers only the most liquid pool, so it can understate tokens that trade in several pools.</li>
          <li>24h change is the top pool&apos;s change and is shown only when the token is that pool&apos;s base token, because a pool&apos;s change describes its base asset.</li>
          <li>A price of 0 is stored as unknown. Data older than 24 hours is hidden, never shown stale. The thresholds are judgement calls from early data and are published here so they can be challenged.</li>
        </ul>

        <h2 id="venues">DEX volume</h2>
        <p>
          Each venue&apos;s own busiest pools (up to 200) are read from GeckoTerminal every hour and summed. Uniswap V2, V3 and V4 are separate
          venues, as GeckoTerminal and CoinGecko list them. Venues are shown as DEXes unless confirmed as launch platforms.
        </p>
        <p>
          <b>Anomaly filter.</b> Raw sums were wrong on Arc: one venue summed to $27.8M against $0.4M on CoinGecko, because a few pools
          reported millions in volume from two or three wallets. A pool is excluded when it has fewer than 10 traders in 24 hours, or its
          volume exceeds 25 times its reserves (or it has volume and no reserves). The excluded amount is reported beside each venue
          and in the API (<code>excluded_volume_usd</code>), never hidden. Applied to that venue it leaves about $0.5M against
          CoinGecko&apos;s $0.4M; the other venues agreed within about 25% without any filtering, and turnover cutoffs between 10x and 100x
          change nothing, so 25x is not a sensitive choice. CoinGecko&apos;s own rule is not public, so totals can still differ.
        </p>
        <ul>
          <li>A leading &ldquo;≥&rdquo; means the venue has more pools than the scan covers, so the figure is a lower bound.</li>
          <li>Only venues whose scan finished are updated; others keep their previous row, which is hidden after 24 hours. If transaction counts are missing for a venue it is refused rather than reported unfiltered.</li>
          <li>Liquidity is deliberately not summed per venue: reserves are self-reported and one spoofed pool distorts a sum.</li>
        </ul>

        <h2 id="freshness">Freshness</h2>
        <div className="tbl">
          <table>
            <thead><tr><th>Data</th><th>Refresh</th><th>Hidden when older than</th></tr></thead>
            <tbody>
              <tr><td>Network and project activity</td><td>Continuous</td><td>n/a (days after <code>data_through</code> are partial)</td></tr>
              <tr><td>TVL and score</td><td>Every 4 hours</td><td>n/a (shows the latest run&apos;s time)</td></tr>
              <tr><td>Market data and venues</td><td>Hourly</td><td>24 hours</td></tr>
              <tr><td>7-day token volume</td><td>About every 6 hours</td><td>48 hours</td></tr>
              <tr><td>Holders</td><td>About every 12 hours</td><td>72 hours</td></tr>
              <tr><td>Links</td><td>Weekly</td><td>n/a</td></tr>
            </tbody>
          </table>
        </div>
        <p>
          The status pill reads <code>/metrics/status</code>: the timestamp of the last block applied and how far behind now that is. It says
          <b> live</b> only when that lag is under ten minutes. Scheduled jobs on GitHub Actions are best effort, so the worker chains its own
          runs to keep following the tip.
        </p>

        <h2 id="limits">Known limits</h2>
        <ul>
          <li><b>Coverage starts on 27 September 2026.</b> Earlier days are not backfilled.</li>
          <li><b>USDC movement is gross,</b> and counts router and pool hops.</li>
          <li><b>Blocklist reverts</b> consume gas without producing a receipt, so those transactions are absent from transaction and gas totals. This is a small gap, documented by Arc.</li>
          <li><b>Unique users</b> are senders that called a project&apos;s contracts directly. Calls through a router are attributed to the router.</li>
          <li><b>Token and DEX data is third-party.</b> Isogram can only be as accurate as GeckoTerminal, and filters what it can prove is anomalous.</li>
          <li><b>Names are deployer-chosen.</b> Verify an address before trusting a name; the search box accepts a contract address.</li>
          <li><b>Scores are relative</b> to a small group and not comparable across the 8 October 2026 change.</li>
          <li><b>Single instance.</b> The API runs on free hosting and can take a few seconds to wake; rate limits are per process.</li>
        </ul>
        <p>Isogram is research and ecosystem infrastructure. Nothing on it is a trading signal or financial advice.</p>
      </div>
    </>
  );
}
