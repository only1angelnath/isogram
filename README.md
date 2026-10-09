# Isogram

The data truth layer for Arc: USDC gas and flow analytics, TVL tracking for DeFi
protocols, and an Arc Native Score with an embeddable badge, all served from one
public API. Built for the Arc Mainnet Microgrants program.

- **Dashboard:** https://isogram.vercel.app
- **API:** https://isogramapi.onrender.com (interactive docs at `/docs`)
- **Is the data live?** `GET /metrics/status` reports the last processed block and
  the exact lag. The dashboard's status pill reads the same endpoint.

## What it does

- **Network analytics:** daily transactions, gas, USDC volume and active addresses for
  Arc mainnet, plus a gas leaderboard and per-token daily activity.
- **Projects:** every contract that shows meaningful activity is discovered
  automatically, classified (DeFi, launchpad, infrastructure, stablecoin, token), and
  shown with the metrics that fit its type. Project owners can propose a contract through
  `POST /submit`; submissions go to a human review queue and are never listed
  automatically.
- **TVL and Arc Native Score (DeFi only):** live on-chain balances for DeFi protocols and
  a composite score of gas, users, TVL and contract age, normalised against other DeFi
  protocols. Every project has an SVG badge you can embed; it shows the score for DeFi
  protocols and "not scored" for other types:

  ```markdown
  ![Isogram score](https://isogramapi.onrender.com/badge/<project-id>.svg)
  ```

## How it works

```
Arc mainnet RPC -> ingestion worker -> per-day rollups -> Postgres (Supabase)
                                                              |
                                      FastAPI (Render) <------+
                                          |
                                dashboard (Vercel) and badge endpoint
```

- **Ingestion** follows the chain tip using `eth_getBlockReceipts` (two RPC calls per
  block), aggregates per-day rollups in memory, and writes them atomically together with
  its checkpoint, so a crash can never double-count or skip a block. It runs as a chain
  of GitHub Actions jobs, each of which starts the next.
- **Scoring** runs every four hours and reads the rollups through SQL functions.
- **No per-transaction rows are stored.** Everything is a rollup, which keeps the whole
  database within a free-tier budget. The whole stack runs at zero recurring cost.

## Methodology and caveats

- **USDC is Arc's native gas asset**, visible two ways: 18 decimals natively and 6
  decimals as an ERC-20. They are the same funds, never two assets. Every stored amount
  uses the 6-decimal view, converted once at ingestion.
- **USDC volume is gross movement.** It is counted from Arc's native system log and
  includes intermediate router hops, so it is not economic volume. The ERC-20 stream on
  its own misses roughly three quarters of movement.
- **Only DeFi protocols are scored and given TVL.** Tokens, infrastructure and other
  types show `null` ("not applicable"), never `0`. With a small peer group the score is
  coarse: treat it as a ranking within DeFi, not an absolute quality measure.
- **Missing data is reported as `null`,** not zero. Active addresses are not available
  for the first days of history (before the rollup pipeline existed), and a project's
  user count only covers days it was already tracked.
- **Network and project usage metrics are read directly from the chain.** The exceptions
  are token market data and contract discovery, both from CoinGecko's GeckoTerminal API,
  and both labelled as third-party wherever they appear.
- **Token market data (price, FDV, liquidity, 24h volume) is third-party.** It is shown
  only for token and stablecoin projects, refreshed hourly, and only where GeckoTerminal
  indexes a trading pool; about half of tracked tokens have a priced pool, and most of
  those are thin. Each value carries a quality flag: `thin` means under $10,000 of liquidity and
  `inactive` means under 1% of liquidity traded in 24 hours. FDV and market cap are
  withheld unless quality is `ok`, because they inherit every flaw of the price. Data
  older than 24 hours is hidden. A `CoinGecko` tag means the token maps to a CoinGecko
  listing; without it the price comes from a DEX pool and is unverified. Token names are
  chosen by whoever deploys the contract, so a token called "Bitcoin" is not necessarily
  Bitcoin.
- **Contract discovery** uses GeckoTerminal and CoinGecko metadata to help identify and
  classify contracts before a human confirms them.

## API

| Endpoint | Description |
|---|---|
| `GET /metrics/status` | Pipeline freshness (last block, data-through time, lag) |
| `GET /metrics/network/daily` | Daily network metrics |
| `GET /metrics/tokens/daily` | Daily per-token activity |
| `GET /metrics/contracts/top` | Most active contracts |
| `GET /projects`, `/projects/{id}` | Tracked projects and detail (token and stablecoin projects include a `market` object) |
| `GET /projects/{id}/daily` | Daily metrics for one project |
| `GET /gas/top`, `/tvl/top`, `/scores/top` | Leaderboards |
| `GET /scores/{id}/history` | Score history for a project |
| `GET /badge/{id}.svg` | Embeddable score badge |
| `POST /submit` | Propose a contract for listing (rate-limited, review queue) |

CORS is open by design: this is a public data API meant to be embedded. Nothing
authenticates by cookie, `/admin/*` requires an `X-Admin-Key` header, and `/submit` can
only create a pending row for human review.

## Run it locally

You need Python 3.12 and a recent Node.js.

```bash
cp .env.example .env              # Supabase URL and service key at minimum

# API
cd api && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

# Ingestion worker (one pass) and scoring
cd ingestion && pip install -r requirements.txt && python worker.py
cd scoring && pip install -r requirements.txt && python compute_scores.py

# Dashboard (set API_BASE_URL in dashboard/.env.local)
cd dashboard && npm install && npm run dev
```

Database schema lives in `supabase/migrations/` and is applied with the Supabase CLI.

## Tests

```bash
cd api && python -m pytest -q
cd ingestion && python -m pytest -q
cd scoring && python -m pytest -q
```

## Repository layout

| Path | Contents |
|---|---|
| `ingestion/` | Chain follower, per-day rollups, contract discovery, admin tools |
| `scoring/` | Segments, TVL, and the Arc Native Score job |
| `api/` | FastAPI service (public reads, `/submit`, `/admin`) |
| `dashboard/` | Next.js dashboard |
| `supabase/migrations/` | Postgres schema and SQL functions |
| `ops/` | One-off SQL used during backfills |
| `.github/workflows/` | Ingestion chain and scoring schedule |
| `bot/` | Early Telegram bot prototype. Not part of this submission and not deployed. |
