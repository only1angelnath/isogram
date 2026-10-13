-- API keys for the public Isogram API (self-service registration, POST /keys).
-- Only the SHA-256 hash of a key is stored; the key itself is shown once, at creation.
-- RLS is on with NO policies and anon/authenticated privileges are revoked, so only the service key
-- (used by the API's write client) can read or write this table. Supabase default privileges would
-- otherwise grant anon access; the explicit revoke is the belt to RLS's braces.

create table if not exists public.api_keys (
  id                    bigint generated always as identity primary key,
  key_hash              text not null unique,
  key_prefix            text not null,
  name                  text not null check (char_length(name) between 2 and 60),
  contact               text check (contact is null or char_length(contact) <= 120),
  tier                  text not null default 'registered' check (tier in ('registered', 'partner')),
  rate_limit_per_minute integer check (rate_limit_per_minute is null or rate_limit_per_minute > 0),
  created_at            timestamptz not null default now(),
  last_used_at          timestamptz,
  revoked_at            timestamptz
);

alter table public.api_keys enable row level security;
revoke all on public.api_keys from anon, authenticated;
