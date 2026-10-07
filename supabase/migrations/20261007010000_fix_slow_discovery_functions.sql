-- 20261007010000_fix_slow_discovery_functions.sql
--
-- INCIDENT 2026-10-07: every ingestion run ran its full 55 min, then FAILED right after,
-- so the success-only chain never fired and the data went stale for hours. Cause:
-- discovery's first step calls unmapped_contract_activity(), which tested "is this
-- contract already a project?" (`= any(projects.contracts)`) for EVERY ROW of
-- daily_contract_metrics BEFORE aggregating. At ~1M rows x ~600 projects that took 94 s
-- (measured), far past the API statement timeout. It worked on 10/6 only because the table
-- was nearly empty. Same shape of flaw in top_contracts (lateral join per row before
-- LIMIT) and project_daily_metrics (no day filter -> scan of the whole table).
-- Fixes: aggregate first, anti-join once per contract against a hashed set, LIMIT before
-- joining, use the (day, contract) primary key. Results are unchanged (tested against
-- the old functions); only the cost changes.

-- ---- 1. discovery's unmapped-contract read -------------------------------------------
drop function if exists public.unmapped_contract_activity(integer, integer);

create or replace function public.unmapped_contract_activity(
  p_days   integer default 14,
  p_limit  integer default 1000,
  p_min_tx integer default 3        -- the 1-2 tx long tail is wallets / noise; discovery needs >= 15
)
returns table (contract_address text, call_count bigint, first_seen timestamptz, last_seen timestamptz)
language sql
stable
set search_path = public
as $$
  with mapped as (
    select lower(c.addr) as addr
    from projects p cross join lateral unnest(p.contracts) c(addr)
  ),
  agg as (
    select m.contract_address as addr, sum(m.tx_count) as calls, min(m.day) as d0, max(m.day) as d1
    from daily_contract_metrics m
    where m.day >= (now() at time zone 'utc')::date - p_days
    group by m.contract_address
    having sum(m.tx_count) >= p_min_tx
  )
  select a.addr,
         a.calls::bigint,
         (a.d0::text || ' 00:00:00+00')::timestamptz,
         (a.d1::text || ' 23:59:59+00')::timestamptz
  from agg a
  where not exists (select 1 from mapped x where x.addr = a.addr)
  order by a.calls desc, a.addr
  limit least(p_limit, 1000)
$$;

revoke execute on function public.unmapped_contract_activity(integer, integer, integer) from public, anon, authenticated;
grant  execute on function public.unmapped_contract_activity(integer, integer, integer) to service_role;

-- ---- 2. top contracts: pick the top N FIRST, then look up their project -------------
create or replace function public.top_contracts(p_days integer default 7, p_limit integer default 20)
returns table (
  contract_address text, project_id text, project_name text, category text,
  tx_count bigint, failed_tx_count bigint, usdc_gas text, gas_share numeric
)
language sql
stable
security definer
set search_path = public
as $$
  with d0 as (select (now() at time zone 'utc')::date - (greatest(p_days, 1) - 1) as d),
  agg as (
    select m.contract_address as addr,
           sum(m.tx_count) as tx, sum(m.failed_tx_count) as failed, sum(m.usdc_gas_paid) as gas
    from daily_contract_metrics m, d0
    where m.day >= d0.d
    group by m.contract_address
  ),
  tot as (
    select coalesce(sum(n.usdc_gas_paid), 0) as gas
    from daily_network_metrics n, d0 where n.day >= d0.d
  ),
  top as (
    select * from agg order by gas desc, addr limit least(greatest(p_limit, 1), 100)
  )
  select t.addr, p.id, p.name, p.category,
         t.tx::bigint, t.failed::bigint, t.gas::text,
         case when tot.gas > 0 then round(t.gas / tot.gas, 6) end
  from top t
  cross join tot
  left join lateral (
    select pr.id, pr.name, pr.category from projects pr where t.addr = any (pr.contracts) limit 1
  ) p on true
  order by t.gas desc, t.addr
$$;

-- ---- 3. one project's daily series: primary-key lookups, not a table scan ------------
create or replace function public.project_daily_metrics(p_project_id text, p_days integer default 30)
returns table (day date, tx_count bigint, failed_tx_count bigint, usdc_gas text, unique_users bigint)
language sql
stable
security definer
set search_path = public
as $$
  with d0 as (select (now() at time zone 'utc')::date - (least(greatest(p_days, 1), 90) - 1) as d),
  pc as (
    select lower(c.addr) as addr
    from projects p cross join lateral unnest(p.contracts) c(addr)
    where p.id = p_project_id
  ),
  cal as (select n.day as cday from daily_network_metrics n, d0 where n.day >= d0.d),
  act as (
    select cal.cday as aday, sum(m.tx_count) as tx, sum(m.failed_tx_count) as failed, sum(m.usdc_gas_paid) as gas
    from cal cross join pc
    join daily_contract_metrics m on m.day = cal.cday and m.contract_address = pc.addr
    group by cal.cday
  ),
  usr as (
    select cal.cday as uday, count(distinct u.address) as users
    from cal cross join pc
    join daily_contract_users u on u.day = cal.cday and u.contract_address = pc.addr
    group by cal.cday
  )
  select cal.cday,
         coalesce(act.tx, 0)::bigint, coalesce(act.failed, 0)::bigint,
         coalesce(act.gas, 0)::text, coalesce(usr.users, 0)::bigint
  from cal
  left join act on act.aday = cal.cday
  left join usr on usr.uday = cal.cday
  order by cal.cday
$$;

-- ---- 4. long-tail pruning in BOUNDED chunks -------------------------------------------
-- One unbounded DELETE over a day's worth of 1-2 tx wallet rows can itself exceed the
-- statement timeout. Each call now deletes at most p_max_rows and reports whether more
-- remain; the worker calls it in a short loop.
drop function if exists public.prune_rollup_long_tail(integer, integer);

create or replace function public.prune_rollup_long_tail(
  p_min_tx         integer default 3,
  p_keep_full_days integer default 2,
  p_max_rows       integer default 50000
) returns jsonb
language plpgsql
set search_path = public
as $$
declare n bigint;
begin
  with doomed as (
    select day, contract_address
    from daily_contract_metrics
    where day < (now() at time zone 'utc')::date - p_keep_full_days
      and tx_count < p_min_tx
    limit p_max_rows
  )
  delete from daily_contract_metrics m
  using doomed d
  where m.day = d.day and m.contract_address = d.contract_address;
  get diagnostics n = row_count;
  return jsonb_build_object('long_tail_rows_deleted', n, 'more', n >= p_max_rows);
end;
$$;

revoke execute on function public.prune_rollup_long_tail(integer, integer, integer) from public, anon, authenticated;
grant  execute on function public.prune_rollup_long_tail(integer, integer, integer) to service_role;
