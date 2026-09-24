-- Network-wide stats for the dashboard's stat strip (docs/BRANDING.md §5's
-- "honest stat strip" — real facts only). These are NETWORK totals, not
-- per-project, so they don't belong in project_scores (docs/SCHEMA.md) —
-- same single-row-checkpoint pattern as sync_state.
--
-- Deliberately NOT market cap: market cap needs a token price oracle and
-- supply tracking, neither of which exist yet and neither of which is
-- meaningful for the currently-tracked projects (three stablecoins pegged
-- ~$1, one protocol with no token on Arc at all). Treated as a separate
-- future feature, not bundled into this migration.
create table network_stats (
  id                     int primary key default 1,
  total_volume_7d        numeric,   -- sum of token_flows.usd_value, trailing 7d, priced tokens only
  total_tx_7d            integer,   -- count of gas_events, trailing 7d
  total_unique_users_7d  integer,   -- distinct token_flows.from_address, trailing 7d, network-wide
  computed_at            timestamptz not null,
  constraint single_row check (id = 1)
);
