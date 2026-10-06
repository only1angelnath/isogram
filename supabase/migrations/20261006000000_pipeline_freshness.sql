-- 20261006000000_pipeline_freshness.sql
--
-- Data freshness. The API's `partial` flag was calendar-based, so while ingestion
-- was catching up it reported 2026-10-05 as complete with only 76,002 of ~170,000
-- blocks. sync_state now records the TIMESTAMP of the last applied block
-- (written atomically with the checkpoint), and pipeline_status() exposes it, so
-- "how stale is this data" is a measured number instead of an assumption.
--
-- apply_ingest_batch gains an optional 8th argument (default null), so a worker
-- still calling it with the original 7 keeps working - apply this BEFORE
-- deploying the new worker.

alter table public.sync_state add column if not exists last_block_ts timestamptz;

drop function if exists public.apply_ingest_batch(bigint, bigint, jsonb, jsonb, jsonb, jsonb, jsonb);

create or replace function public.apply_ingest_batch(
  p_start_block   bigint,
  p_end_block     bigint,
  p_contracts     jsonb,  -- [{day, contract_address, tx_count, failed_tx_count, usdc_gas_paid}]
  p_network       jsonb,  -- [{day, tx_count, failed_tx_count, usdc_gas_paid, contract_creations, blocks, token_transfer_count}]
  p_tokens        jsonb,  -- [{day, token_address, transfer_count, volume}]
  p_addresses     jsonb,  -- {"YYYY-MM-DD": ["<40 hex chars>", ...]}
  p_contract_users jsonb, -- {"YYYY-MM-DD": {"<contract>": ["<40 hex>", ...]}}
  p_end_block_ts  timestamptz default null  -- timestamp of p_end_block (freshness)
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

  update sync_state
    set last_block_number = p_end_block,
        last_block_ts     = coalesce(p_end_block_ts, last_block_ts),
        updated_at        = now()
    where id = 1;
end;
$$;

revoke execute on function public.apply_ingest_batch(bigint, bigint, jsonb, jsonb, jsonb, jsonb, jsonb, timestamptz) from public, anon, authenticated;
grant  execute on function public.apply_ingest_batch(bigint, bigint, jsonb, jsonb, jsonb, jsonb, jsonb, timestamptz) to service_role;

-- Public, read-only, one row: how far the data has been processed. SECURITY
-- DEFINER because sync_state deliberately has no anon policy (internal
-- checkpoint); this exposes only the block number and timestamps.
create or replace function public.pipeline_status()
returns table (
  last_block_number     bigint,
  data_through          timestamptz,
  checkpoint_updated_at timestamptz
)
language sql
stable
security definer
set search_path = public
as $$
  select last_block_number, last_block_ts, updated_at from sync_state where id = 1
$$;

revoke execute on function public.pipeline_status() from public, anon, authenticated;
grant  execute on function public.pipeline_status() to anon, authenticated, service_role;
