-- 24h price change (%) per token, taken from the token's most liquid pool (GeckoTerminal
-- `include=top_pools`, pool attribute price_change_percentage.h24). Stored only when the token is the
-- BASE token of that pool (the pool's change describes its base token; for a token that is the quote
-- side of its top pool the number would belong to the other asset). Signed: negative is a fall.
-- Grants from 20261009000000 already cover new columns.

alter table public.token_market_data
  add column if not exists price_change_24h_pct numeric;
