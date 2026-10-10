-- token_holders: number of addresses holding each token, from Arc's own explorer
-- (explorer.arc.io Blockscout /api/v2/tokens/{address}.holders_count). Separate from
-- token_market_data because it applies to every token, including the ones no DEX pool prices.
-- holders_count is NULL when the explorer does not index the address as a token (404): the row
-- is kept so those addresses are not re-queried on every run (they come due again after the
-- normal refresh interval).

create table if not exists public.token_holders (
  contract_address text primary key,
  holders_count    bigint,
  source           text not null default 'explorer.arc.io',
  fetched_at       timestamptz not null default now(),
  constraint token_holders_address_lowercase check (contract_address = lower(contract_address)),
  constraint token_holders_count_non_negative check (holders_count is null or holders_count >= 0)
);

comment on table public.token_holders is
  'Holder counts from the Arc explorer (Blockscout). NULL = not indexed as a token. Refreshed ~every 12h.';

-- Same posture as token_market_data: RLS on, public SELECT only (default privileges grant ALL).
alter table public.token_holders enable row level security;

drop policy if exists public_read_only on public.token_holders;
create policy public_read_only on public.token_holders
  for select to anon, authenticated using (true);

revoke all on public.token_holders from anon, authenticated;
grant select on public.token_holders to anon, authenticated;
