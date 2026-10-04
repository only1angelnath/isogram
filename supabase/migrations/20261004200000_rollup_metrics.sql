-- 20261004200000_rollup_metrics.sql
--
-- Rollup-first metrics layer. Context (2026-10-04): Arc produces ~12 tx/block
-- (~2M tx/day); gas_events costs ~310 bytes/row, so raw per-transaction
-- storage cannot fit Supabase's 0.5 GB free tier even for ONE day of full
-- chain coverage (DB hit 648 MB). The worker now aggregates in memory and
-- calls apply_ingest_batch() below, which applies the batch's deltas AND
-- advances sync_state in ONE transaction -- exactly-once: a crash can never
-- double-count or skip a batch. gas_events/token_flows stop being written.
--
-- All USDC amounts here are the 6-decimal / human USDC view (see
-- docs/architecture_essentials.md). Native 18-decimal values never land here.
--
-- Additive and safe to apply while the old worker is still running.

-- ---------------------------------------------------------------- tables

-- Per-contract, per-day activity. project_id is deliberately NOT stored:
-- readers join through projects.contracts so a contract promoted later is
-- attributed retroactively (no stale/mis-attributed history).
create table if not exists public.daily_contract_metrics (
  day              date    not null,
  contract_address text    not null,            -- lowercase `to` address
  tx_count         integer not null default 0,
  failed_tx_count  integer not null default 0,
  usdc_gas_paid    numeric not null default 0,  -- 6-decimal USDC view
  primary key (day, contract_address)
);

-- Chain-wide per-day totals.
create table if not exists public.daily_network_metrics (
  day                 date primary key,
  tx_count            bigint  not null default 0,
  failed_tx_count     bigint  not null default 0,
  usdc_gas_paid       numeric not null default 0,
  contract_creations  integer not null default 0,
  blocks              integer not null default 0,
  token_transfer_count bigint not null default 0,
  active_addresses    integer,                  -- distinct tx senders; kept after the address table is pruned
  source              text    not null default 'live'
    check (source in ('live', 'raw_backfill')) -- raw_backfill: failed/creations/blocks unknown (reported as 0)
);

-- Per-token, per-day transfers (tracked tokens only: USDC/EURC/USYC).
create table if not exists public.daily_token_metrics (
  day            date    not null,
  token_address  text    not null,
  transfer_count bigint  not null default 0,
  volume         numeric not null default 0,   -- token's own 6-decimal units
  primary key (day, token_address)
);

-- Distinct tx senders per day (bytea = 20 bytes, far smaller than text).
-- Pruned to a short window by prune_rollup_addresses(); the permanent
-- count lives in daily_network_metrics.active_addresses.
create table if not exists public.daily_active_addresses (
  day     date  not null,
  address bytea not null,
  primary key (day, address)
);

-- Distinct senders per day per TRACKED project contract (set by the worker
-- from contract_project_map only, so this stays small). Feeds unique_users_7d.
create table if not exists public.daily_contract_users (
  day              date  not null,
  contract_address text  not null,
  address          bytea not null,
  primary key (day, contract_address, address)
);

-- ------------------------------------------------------------------- RLS
-- Same posture as 20260925100000_enable_rls.sql: RLS on, SELECT-only for the
-- three public aggregate tables, NO policies at all for the address tables.
alter table public.daily_contract_metrics  enable row level security;
alter table public.daily_network_metrics   enable row level security;
alter table public.daily_token_metrics     enable row level security;
alter table public.daily_active_addresses  enable row level security;
alter table public.daily_contract_users    enable row level security;

drop policy if exists public_read_only on public.daily_contract_metrics;
drop policy if exists public_read_only on public.daily_network_metrics;
drop policy if exists public_read_only on public.daily_token_metrics;
create policy public_read_only on public.daily_contract_metrics for select to anon, authenticated using (true);
create policy public_read_only on public.daily_network_metrics  for select to anon, authenticated using (true);
create policy public_read_only on public.daily_token_metrics    for select to anon, authenticated using (true);

-- Default privileges on this project grant ALL to anon/authenticated; strip
-- writes explicitly (defence in depth on top of RLS).
revoke insert, update, delete, truncate on
  public.daily_contract_metrics, public.daily_network_metrics,
  public.daily_token_metrics, public.daily_active_addresses,
  public.daily_contract_users
from anon, authenticated;
revoke select on public.daily_active_addresses, public.daily_contract_users from anon, authenticated;

-- ------------------------------------------------------- atomic batch apply
create or replace function public.apply_ingest_batch(
  p_start_block   bigint,
  p_end_block     bigint,
  p_contracts     jsonb,  -- [{day, contract_address, tx_count, failed_tx_count, usdc_gas_paid}]
  p_network       jsonb,  -- [{day, tx_count, failed_tx_count, usdc_gas_paid, contract_creations, blocks, token_transfer_count}]
  p_tokens        jsonb,  -- [{day, token_address, transfer_count, volume}]
  p_addresses     jsonb,  -- {"YYYY-MM-DD": ["<40 hex chars>", ...]}
  p_contract_users jsonb  -- {"YYYY-MM-DD": {"<contract>": ["<40 hex>", ...]}}
) returns void
language plpgsql
set search_path = public
as $$
declare
  cur bigint;
  v_day text;
begin
  if p_end_block < p_start_block then
    raise exception 'bad batch: end % < start %', p_end_block, p_start_block;
  end if;

  -- Optimistic concurrency + single-writer lock on the checkpoint row.
  select last_block_number into cur from sync_state where id = 1 for update;
  if cur is null then
    raise exception 'sync_state row (id=1) missing';
  end if;
  if cur <> p_start_block - 1 then
    raise exception 'checkpoint mismatch: sync_state at %, batch starts at % (expected %)',
      cur, p_start_block, cur + 1;
  end if;

  insert into daily_contract_metrics (day, contract_address, tx_count, failed_tx_count, usdc_gas_paid)
  select (r->>'day')::date, r->>'contract_address',
         sum((r->>'tx_count')::int), sum((r->>'failed_tx_count')::int), sum((r->>'usdc_gas_paid')::numeric)
  from jsonb_array_elements(coalesce(p_contracts, '[]'::jsonb)) r
  group by 1, 2
  on conflict (day, contract_address) do update set
    tx_count        = daily_contract_metrics.tx_count        + excluded.tx_count,
    failed_tx_count = daily_contract_metrics.failed_tx_count + excluded.failed_tx_count,
    usdc_gas_paid   = daily_contract_metrics.usdc_gas_paid   + excluded.usdc_gas_paid;

  insert into daily_network_metrics (day, tx_count, failed_tx_count, usdc_gas_paid,
                                     contract_creations, blocks, token_transfer_count)
  select (r->>'day')::date,
         sum((r->>'tx_count')::bigint), sum((r->>'failed_tx_count')::bigint),
         sum((r->>'usdc_gas_paid')::numeric), sum((r->>'contract_creations')::int),
         sum((r->>'blocks')::int), sum((r->>'token_transfer_count')::bigint)
  from jsonb_array_elements(coalesce(p_network, '[]'::jsonb)) r
  group by 1
  on conflict (day) do update set
    tx_count             = daily_network_metrics.tx_count             + excluded.tx_count,
    failed_tx_count      = daily_network_metrics.failed_tx_count      + excluded.failed_tx_count,
    usdc_gas_paid        = daily_network_metrics.usdc_gas_paid        + excluded.usdc_gas_paid,
    contract_creations   = daily_network_metrics.contract_creations   + excluded.contract_creations,
    blocks               = daily_network_metrics.blocks               + excluded.blocks,
    token_transfer_count = daily_network_metrics.token_transfer_count + excluded.token_transfer_count;

  insert into daily_token_metrics (day, token_address, transfer_count, volume)
  select (r->>'day')::date, r->>'token_address',
         sum((r->>'transfer_count')::bigint), sum((r->>'volume')::numeric)
  from jsonb_array_elements(coalesce(p_tokens, '[]'::jsonb)) r
  group by 1, 2
  on conflict (day, token_address) do update set
    transfer_count = daily_token_metrics.transfer_count + excluded.transfer_count,
    volume         = daily_token_metrics.volume         + excluded.volume;

  -- Set semantics: re-applying the same addresses is a no-op.
  insert into daily_active_addresses (day, address)
  select d.key::date, decode(a.value, 'hex')
  from jsonb_each(coalesce(p_addresses, '{}'::jsonb)) d,
       jsonb_array_elements_text(d.value) a(value)
  on conflict do nothing;

  insert into daily_contract_users (day, contract_address, address)
  select d.key::date, c.key, decode(a.value, 'hex')
  from jsonb_each(coalesce(p_contract_users, '{}'::jsonb)) d,
       jsonb_each(d.value) c,
       jsonb_array_elements_text(c.value) a(value)
  on conflict do nothing;

  -- Persist the distinct-sender count for every day this batch touched
  -- (survives later pruning of daily_active_addresses).
  for v_day in select jsonb_object_keys(coalesce(p_addresses, '{}'::jsonb)) loop
    insert into daily_network_metrics (day, active_addresses)
    values (v_day::date, (select count(*) from daily_active_addresses where day = v_day::date))
    on conflict (day) do update set active_addresses = excluded.active_addresses;
  end loop;

  update sync_state set last_block_number = p_end_block, updated_at = now() where id = 1;
end;
$$;

-- Short retention for the two address tables (counts are already persisted).
create or replace function public.prune_rollup_addresses(p_keep_days integer default 8)
returns jsonb
language plpgsql
set search_path = public
as $$
declare a bigint; u bigint;
begin
  delete from daily_active_addresses where day < (now() at time zone 'utc')::date - p_keep_days;
  get diagnostics a = row_count;
  delete from daily_contract_users where day < (now() at time zone 'utc')::date - p_keep_days;
  get diagnostics u = row_count;
  return jsonb_build_object('active_addresses_deleted', a, 'contract_users_deleted', u);
end;
$$;

-- CRITICAL: this project's default privileges grant EXECUTE on new functions
-- to anon/authenticated (see schema dump). These mutate data -- service_role only.
revoke execute on function public.apply_ingest_batch(bigint, bigint, jsonb, jsonb, jsonb, jsonb, jsonb) from public, anon, authenticated;
revoke execute on function public.prune_rollup_addresses(integer) from public, anon, authenticated;
grant  execute on function public.apply_ingest_batch(bigint, bigint, jsonb, jsonb, jsonb, jsonb, jsonb) to service_role;
grant  execute on function public.prune_rollup_addresses(integer) to service_role;
