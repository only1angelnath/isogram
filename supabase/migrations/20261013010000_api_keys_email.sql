-- API keys now require an email, so key holders can be contacted about the API (changes, limits, abuse).
-- The address is NOT verified: it is a contact point, never an identity. Only the service key can read it
-- (the table has RLS on with no policies and anon/authenticated privileges revoked, see 20261013000000).
-- Nullable because keys created before this migration, if any, have none.

alter table public.api_keys add column if not exists email text;
alter table public.api_keys
  add constraint api_keys_email_len check (email is null or char_length(email) <= 254);
create index if not exists api_keys_email_idx on public.api_keys (email) where revoked_at is null;
