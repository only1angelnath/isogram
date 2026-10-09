-- Store GeckoTerminal's coingecko_coin_id for each token. A non-null value means the token
-- is mapped to a listed CoinGecko coin, which is the only verification signal in the payload:
-- the dashboard marks those as "CoinGecko-listed" and treats the rest as unverified (a token
-- called "Bitcoin" on Arc is just a name chosen by whoever deployed it).
-- Column-level SELECT is already covered by the table grant from 20261009000000.

alter table public.token_market_data
  add column if not exists coingecko_coin_id text;
