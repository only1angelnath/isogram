-- venue_market_data: 24h trading volume per DEX / launchpad venue on Arc, summed from
-- GeckoTerminal's network-wide top pools (sorted by 24h volume, up to 10 pages of 20). Third-party,
-- like token_market_data. sample_pools is how many pools the sums were taken from, so the UI can say
-- "top N pools" honestly: venues with a long tail of tiny pools are slightly understated.
-- Liquidity is deliberately not stored per venue: pool reserves are self-reported and a single
-- spoofed pool distorts any sum (a token with $39M of "liquidity" and $1 of volume exists on Arc).

create table if not exists public.venue_market_data (
  dex_id              text primary key,
  name                text not null,
  kind                text not null check (kind in ('dex', 'launchpad')),
  volume_24h_usd      numeric not null default 0,
  active_pools        integer not null default 0,   -- sampled pools with volume > 0
  sample_pools        integer not null default 0,   -- pools scanned network-wide this run
  top_pool_name       text,
  top_pool_volume_usd numeric,
  source              text not null default 'geckoterminal',
  fetched_at          timestamptz not null default now(),
  constraint venue_market_data_volume_non_negative check (volume_24h_usd >= 0)
);

comment on table public.venue_market_data is
  'Per-venue 24h volume from GeckoTerminal top pools (third-party). Sums cover sample_pools pools only.';

alter table public.venue_market_data enable row level security;

drop policy if exists public_read_only on public.venue_market_data;
create policy public_read_only on public.venue_market_data
  for select to anon, authenticated using (true);

revoke all on public.venue_market_data from anon, authenticated;
grant select on public.venue_market_data to anon, authenticated;
