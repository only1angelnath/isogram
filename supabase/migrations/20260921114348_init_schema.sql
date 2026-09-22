create table projects (
  id            text primary key,
  name          text not null,
  contracts     text[] not null,
  category      text,
  socials       jsonb default '{}',
  created_at    timestamptz default now()
);

create table gas_events (
  tx_hash           text primary key,
  contract_address  text not null,
  project_id        text references projects(id),
  usdc_gas_paid     numeric not null,
  block_number      bigint not null,
  ts                timestamptz not null
);
create index on gas_events (project_id);
create index on gas_events (block_number);
create index on gas_events (ts);

create table token_flows (
  id                bigserial primary key,
  token_address     text not null,
  from_address      text,
  to_address        text,
  amount            numeric,
  usd_value         numeric,
  block_number      bigint,
  ts                timestamptz not null
);
create index on token_flows (token_address);
create index on token_flows (ts);
create index on token_flows (from_address);
create index on token_flows (to_address);

create table project_scores (
  project_id          text references projects(id),
  score               numeric not null,
  tvl_usd             numeric,
  usdc_gas_7d         numeric,
  unique_users_7d     integer,
  computed_at         timestamptz not null,
  primary key (project_id, computed_at)
);
create index on project_scores (computed_at);

create table sync_state (
  id                  int primary key default 1,
  last_block_number   bigint not null,
  updated_at          timestamptz default now(),
  constraint single_row check (id = 1)
);

insert into projects (id, name, contracts, category) values
  ('usdc', 'USDC', array['0x3600000000000000000000000000000000000000'], 'stablecoin'),
  ('eurc', 'EURC', array['0xbef5f6d51cb62b58e6a8f77868681825c6fe21c1'], 'stablecoin'),
  ('usyc', 'USYC', array['0x8a5d989bbb96929f689b0200f435f53da42bf490'], 'institutional')
on conflict (id) do nothing;