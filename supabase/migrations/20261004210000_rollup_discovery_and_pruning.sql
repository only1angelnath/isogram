-- 20261004210000_rollup_discovery_and_pruning.sql
--
-- Companion to 20261004200000_rollup_metrics.sql (apply that first).
--
-- 1) unmapped_contract_activity(): replaces discovery.py's old read of
--    gas_events. That read had NO pagination, so PostgREST's silent 1000-row
--    cap meant discovery only ever saw the first ~1000 unmapped transactions
--    (hence "88 touched" per run and call_count computed from a fragment).
--    This aggregates in Postgres over the rollup instead - complete and cheap.
--
-- 2) prune_rollup_long_tail(): `to` addresses include plain wallets, so
--    daily_contract_metrics can accumulate one-off rows. Once a day is
--    closed (older than p_keep_full_days), rows with fewer than p_min_tx
--    transactions are dropped. Network-wide totals in daily_network_metrics
--    stay exact; per-contract rows are a long-tail-trimmed view.

create or replace function public.unmapped_contract_activity(p_days integer default 14)
returns table (
  contract_address text,
  call_count       bigint,
  first_seen       timestamptz,
  last_seen        timestamptz
)
language sql
stable
set search_path = public
as $$
  select m.contract_address,
         sum(m.tx_count)::bigint,
         (min(m.day)::text || ' 00:00:00+00')::timestamptz,
         (max(m.day)::text || ' 23:59:59+00')::timestamptz
  from daily_contract_metrics m
  where m.day >= (now() at time zone 'utc')::date - p_days
    and not exists (
      select 1 from projects p where m.contract_address = any (p.contracts)
    )
  group by m.contract_address
$$;

create or replace function public.prune_rollup_long_tail(
  p_min_tx integer default 3,
  p_keep_full_days integer default 2
) returns jsonb
language plpgsql
set search_path = public
as $$
declare n bigint;
begin
  delete from daily_contract_metrics
  where day < (now() at time zone 'utc')::date - p_keep_full_days
    and tx_count < p_min_tx;
  get diagnostics n = row_count;
  return jsonb_build_object('long_tail_rows_deleted', n);
end;
$$;

-- Same lock-down as the other rollup functions (default privileges on this
-- project grant EXECUTE to anon/authenticated). The read function is also
-- service_role-only: discovery runs server-side with the service key.
revoke execute on function public.unmapped_contract_activity(integer) from public, anon, authenticated;
revoke execute on function public.prune_rollup_long_tail(integer, integer) from public, anon, authenticated;
grant  execute on function public.unmapped_contract_activity(integer) to service_role;
grant  execute on function public.prune_rollup_long_tail(integer, integer) to service_role;
