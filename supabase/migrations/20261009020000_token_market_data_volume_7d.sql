-- 7-day trading volume per token. GeckoTerminal's multi-token endpoint only reports 24h, so the
-- 7d figure is the sum of the last 7 UTC-day candles of the token's MOST LIQUID POOL
-- (token OHLCV endpoint) - it can understate tokens that trade in several pools. It is refreshed
-- on its own slower schedule, hence its own timestamp. Grants from 20261009000000 already
-- cover new columns.

alter table public.token_market_data
  add column if not exists volume_7d_usd numeric,
  add column if not exists volume_7d_fetched_at timestamptz;
