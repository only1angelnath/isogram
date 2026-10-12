-- token_socials: website / X / Telegram / Discord links that a token's deployer registered with
-- GeckoTerminal (token info). SELF-REPORTED and unverified: anyone can register a link for a token they
-- deployed, so the API re-validates every value (https only, known-host handles) before the dashboard shows
-- it, and labels it self-reported. Rows with all columns NULL mean "looked, found nothing" so those tokens
-- are not re-queried every run; they come due again after the refresh interval (7 days).

create table if not exists public.token_socials (
  contract_address text primary key,
  website          text,
  twitter          text,   -- handle, as registered
  telegram         text,   -- handle, as registered
  discord          text,   -- invite URL, as registered
  source           text not null default 'geckoterminal',
  fetched_at       timestamptz not null default now(),
  constraint token_socials_address_lowercase check (contract_address = lower(contract_address))
);

comment on table public.token_socials is
  'Self-reported social links from GeckoTerminal token info. Unverified; the API sanitises before display.';

alter table public.token_socials enable row level security;

drop policy if exists public_read_only on public.token_socials;
create policy public_read_only on public.token_socials
  for select to anon, authenticated using (true);

revoke all on public.token_socials from anon, authenticated;
grant select on public.token_socials to anon, authenticated;
