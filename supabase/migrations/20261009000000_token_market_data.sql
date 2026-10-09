-- token_market_data: third-party market data (price, FDV, liquidity) for token and
-- stablecoin projects. NOT derived from the chain: it comes from GeckoTerminal (via
-- CoinGecko's onchain API) and is refreshed hourly by the ingestion worker. One row
-- per token contract; a row that stops being refreshed keeps its old values and its
-- old fetched_at, so readers can tell how stale it is and hide it.

create table if not exists public.token_market_data (
  contract_address text primary key,
  symbol           text,
  price_usd        numeric,
  fdv_usd          numeric,
  market_cap_usd   numeric,
  liquidity_usd    numeric,   -- GeckoTerminal total_reserve_in_usd: this token's reserves across all pools
  volume_24h_usd   numeric,
  source           text not null default 'geckoterminal',
  fetched_at       timestamptz not null default now(),
  constraint token_market_data_address_lowercase check (contract_address = lower(contract_address))
);

comment on table public.token_market_data is
  'Third-party market data (GeckoTerminal). Not chain-derived. Stale rows keep their old fetched_at.';

-- Same posture as the rollup tables (20261004200000_rollup_metrics.sql): RLS on,
-- public SELECT only. Default privileges on this project grant ALL to anon and
-- authenticated, so strip everything and grant back SELECT explicitly.
alter table public.token_market_data enable row level security;

drop policy if exists public_read_only on public.token_market_data;
create policy public_read_only on public.token_market_data
  for select to anon, authenticated using (true);

revoke all on public.token_market_data from anon, authenticated;
grant select on public.token_market_data to anon, authenticated;
