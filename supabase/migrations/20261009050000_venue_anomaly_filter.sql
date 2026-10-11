-- Venue volume now excludes anomalous pools (pools with very few traders, or whose 24h volume dwarfs
-- their reserves). The excluded volume is stored too so the dashboard can show it instead of hiding it,
-- and `truncated` marks venues whose pool list was longer than the scan cap (their volume is a lower bound).
-- Grants from 20261009040000 already cover new columns.

alter table public.venue_market_data
  add column if not exists excluded_volume_usd numeric not null default 0,
  add column if not exists excluded_pools      integer not null default 0,
  add column if not exists truncated           boolean not null default false;

alter table public.venue_market_data
  drop constraint if exists venue_market_data_excluded_non_negative;
alter table public.venue_market_data
  add constraint venue_market_data_excluded_non_negative check (excluded_volume_usd >= 0);
