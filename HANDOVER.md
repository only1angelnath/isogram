# Isogram handover

Last updated: 2026-10-18. Read this first when resuming. The README explains what the
product is and how it works; this file says where the work stands and what to do next.

## State at a glance

- **Isogram** is the data truth layer for Arc mainnet (chain 5042): network analytics, a
  project directory, TVL and an Arc Native Score for DeFi, one public API.
- Submitted to the Arc Mainnet Microgrants (deadline was 2026-10-14 23:59 ET).
- Everything below is deployed: dashboard (Vercel), API (Render), ingestion and scoring
  (GitHub Actions), database (Supabase).
- Latest work, all pushed and deployed: `/submit` page and badge embed box, `sitemap.xml`
  and `robots.txt`, the admin curation desk (Submissions, Discovered, Classify, API keys),
  then login attempt limit, sign-out, Restore for dismissed contracts and reply links.
- API test suite: 223 passing. Dashboard `tsc --noEmit` clean.

## How the pieces fit

```
Arc RPC -> ingestion worker -> per-day rollups -> Postgres (Supabase)
                                                      |
        scoring job (every 4 h) --------------------> | <-- FastAPI (Render) <-- dashboard (Vercel)
```

| Part | Path | Runs on | Cadence |
|---|---|---|---|
| Ingestion, rollups, discovery, market data | `ingestion/` | GitHub Actions `ingestion-cron.yml` | Self-chaining jobs, up to 75 min each |
| Score and TVL | `scoring/` | GitHub Actions `scoring-cron.yml` | Every 4 hours |
| API | `api/` | Render, one instance | Always on |
| Dashboard, `/submit`, `/admin` | `dashboard/` | Vercel | On demand |
| Schema and SQL functions | `supabase/migrations/` | Supabase | Applied with the Supabase CLI |

Key rules to keep:

- No per-transaction rows are stored; everything is a rollup. `apply_ingest_batch()` commits
  deltas and the checkpoint in one transaction (exactly-once).
- USDC is the native gas asset: one pool of funds seen as 18 decimals natively and 6 as an
  ERC-20. Store the 6-decimal view only, converted once in `ingestion/decode.py`. Never sum
  the two views.
- Only DeFi is scored and given TVL. Non-DeFi values are `null`, never `0`.
- `api/aggregate.py::SEGMENT_BY_CATEGORY` and `scoring/segments.py::SEGMENT_BY_CATEGORY`
  must match; a test fails if they drift.
- Admin actions only queue. Only `promote_ready_candidates()` inserts into `projects`.
- Every write route must be added on purpose to `ALLOWED_WRITES` in
  `api/tests/test_routes.py`.

## Running things

```bash
cd api && python -m pytest -q                       # API suite (real app, in-memory fake DB)
cd ingestion && python -m pytest -q
cd scoring && python -m pytest -q
cd dashboard && npx tsc --noEmit && npm run build
```

Deploy order when an API route and its UI ship together: Render first, then Vercel.
Environment variables are listed in the README and `.env.example`.

## Operating notes

- **Is data live?** `GET /metrics/status` reports the last block and the lag.
- **Ingestion chain:** each job starts the next with `gh workflow run`. GitHub's `*/5` cron has
  fired only every 3 to 5 hours, so the chain is the real scheduler. If ingestion goes quiet,
  start `ingestion-cron.yml` manually from the Actions tab.
- **Gap backfill:** `backfill-rollup.yml` is manual, uses its own checkpoint, and needs
  `ops/start_gap_backfill.sql` run first.
- **Curation flow:** discovery collects contracts with 15 or more calls, classifies each once
  and moves it to `needs_review`. A person sets a category in `/admin` for the ones with none,
  and the next run promotes them. Restoring a dismissed contract sends it to `unclassified`.
- **Rate limits** (anonymous 60, badge 300, registered 600, internal 6000 per minute, admin
  30) are per process. That is fine for one Render instance; move them to shared storage
  before scaling out.
- **Admin login limiter** is in memory per server instance. A long random
  `ADMIN_DASHBOARD_PASSWORD` is the real protection. It relies on the host overwriting
  `x-forwarded-for`; this was believed to hold on Vercel but never verified live.

## Open items for you

- [ ] Revoke the old test API key in the admin Keys tab.
- [ ] Rotate the internal `dash_...` key that was printed during testing, and update
      `INTERNAL_API_KEYS` (Render) and `API_KEY` (Vercel) together.
- [ ] Delete the test submission from the Submissions tab.
- [ ] Confirm the new login limiter behaves on Vercel (try 6 wrong passwords from a spare
      network, expect a 429).

## Deferred until after the microgrant

- Argus venue note.
- PARA and WONK contract addresses (not yet collected).
- Post-grant roadmap.
- Admin v3 ideas, none started: edit or delist live projects (needs a delist flag and a
  migration), new-submission alerts, bulk actions, an audit log.

## Known limits

- USDC volume is gross movement including router hops, not economic volume.
- Active addresses are unavailable for the earliest days, before the rollup pipeline existed.
- Token market data covers only tokens GeckoTerminal indexes with a pool (about half), and
  most are thin. Venue totals can differ from CoinGecko's own filter.
- The score ranks DeFi protocols against each other and is coarse with a small peer group.
- EURC is treated as 1:1 USD in TVL, a deliberate simplification.

## Where things live that are not in git

`/docs/`, `/mockups/`, `AGENTS.md`, `dump_codebase.sh` and `dump_schema.sh` are gitignored, so
they exist only on the maintainer's machine. Several code comments point at
`docs/ARCHITECTURE.md`, `docs/BUGS.md`, `docs/AUDIT.md` and `docs/decisions/ADR-*.md`; those
files are not in this repository. This file, the README and `supabase/migrations/` are the
tracked sources of truth.

## Gotchas from this build

- A write route added without updating `ALLOWED_WRITES` fails the suite on purpose.
- The dashboard's `.next/types` can go stale after deleting a page and cause fake `tsc`
  errors; remove `.next/types` and rerun.
- Admin endpoints are limited to 30 requests per minute per IP, so avoid firing many calls in
  quick succession from one address.
