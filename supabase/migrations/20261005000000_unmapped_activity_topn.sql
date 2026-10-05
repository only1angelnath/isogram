-- 20261005000000_unmapped_activity_topn.sql
--
-- Fix for the first live rollup run (2026-10-05 00:03 UTC): discovery logged
-- "1000 touched". PostgREST caps EVERY response at 1000 rows - including
-- set-returning functions - and the unordered GROUP BY meant an arbitrary 1000
-- contracts were returned. Return the top-N most active unmapped contracts
-- instead (deterministic, and the ones most worth classifying).
--
-- p_limit must stay <= 1000 (PostgREST max-rows). Old 1-arg signature is
-- dropped so a call with only p_days is never ambiguous.

drop function if exists public.unmapped_contract_activity(integer);

create or replace function public.unmapped_contract_activity(
  p_days  integer default 14,
  p_limit integer default 1000
)
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
         sum(m.tx_count)::bigint as call_count,
         (min(m.day)::text || ' 00:00:00+00')::timestamptz,
         (max(m.day)::text || ' 23:59:59+00')::timestamptz
  from daily_contract_metrics m
  where m.day >= (now() at time zone 'utc')::date - p_days
    and not exists (
      select 1 from projects p where m.contract_address = any (p.contracts)
    )
  group by m.contract_address
  order by sum(m.tx_count) desc, m.contract_address
  limit least(p_limit, 1000)
$$;

revoke execute on function public.unmapped_contract_activity(integer, integer) from public, anon, authenticated;
grant  execute on function public.unmapped_contract_activity(integer, integer) to service_role;
