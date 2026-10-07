-- 20261007000000_historical_gap_backfill.sql
--
-- Fills the hole 2026-09-29 .. 2026-10-03 (blocks 23,225,710 .. 24,297,839): the live
-- checkpoint was jumped past it on 2026-10-04 because replaying it at ~1.3 blocks/s was
-- impossible. At the current ~138 blocks/s it takes ~2 hours.
--
-- apply_backfill_batch() is apply_ingest_batch() for a FIXED historical range: the same
-- additive rollup deltas, but exactly-once against historical_backfill_state (its own
-- checkpoint) instead of sync_state. The two jobs therefore never touch each other's
-- checkpoint and can safely run at the same time; day rows are additive, so interleaved
-- applies from both simply sum. apply_ingest_batch is deliberately NOT modified (it is
-- the live production path); the delta logic below is a copy of it.
--
-- Guard: active_addresses is never written onto a 'raw_backfill' day (a partial count on
-- 2026-09-28 would be wrong).

create or replace function public.apply_backfill_batch(
  p_start_block    bigint,
  p_end_block      bigint,
  p_contracts      jsonb,
  p_network        jsonb,
  p_tokens         jsonb,
  p_addresses      jsonb,
  p_contract_users jsonb
) returns void
language plpgsql
set search_path = public
as $$
declare
  v_next bigint;
  v_end  bigint;
  v_day  text;
begin
  if p_end_block < p_start_block then
    raise exception 'bad batch: end % < start %', p_end_block, p_start_block;
  end if;

  select next_block, range_end into v_next, v_end from historical_backfill_state where id = 1 for update;
  if v_next is null then
    raise exception 'historical_backfill_state row (id=1) missing';
  end if;
  if v_next <> p_start_block then
    raise exception 'backfill checkpoint mismatch: next_block is %, batch starts at %', v_next, p_start_block;
  end if;
  if p_end_block > v_end then
    raise exception 'batch end % is beyond the backfill range end %', p_end_block, v_end;
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
    on conflict (day) do update set active_addresses = excluded.active_addresses
      where daily_network_metrics.source <> 'raw_backfill';  -- never stamp a partial count on a pre-rollup day
  end loop;

  update historical_backfill_state set next_block = p_end_block + 1, updated_at = now() where id = 1;
end;
$$;

revoke execute on function public.apply_backfill_batch(bigint, bigint, jsonb, jsonb, jsonb, jsonb, jsonb) from public, anon, authenticated;
grant  execute on function public.apply_backfill_batch(bigint, bigint, jsonb, jsonb, jsonb, jsonb, jsonb) to service_role;
