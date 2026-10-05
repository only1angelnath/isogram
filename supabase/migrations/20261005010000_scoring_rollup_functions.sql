-- 20261005010000_scoring_rollup_functions.sql
--
-- Scoring/network-stats now read the rollups (apply 20261004200000, ...210000
-- and 20261005000000 first). Aggregation happens in Postgres: one cheap call
-- instead of paging ~1M rows through PostgREST (the old scoring run took
-- 679s and crashed twice on statement timeouts - docs/BUGS.md).
--
-- Windows are N whole UTC days ending today (today is partial): p_days = 7
-- means today-6 .. today. USDC amounts are returned as TEXT so PostgREST
-- never turns a numeric into a lossy float (6-decimal view, docs/BUGS.md #1).
--
-- NOTE: PostgREST caps any response at 1000 rows. project_window_metrics()
-- returns only projects WITH activity in the window; callers treat missing
-- projects as zero.

alter table public.project_scores
  add column if not exists tx_count_7d  bigint,
  add column if not exists failed_tx_7d bigint;

create or replace function public.project_window_metrics(p_days integer default 7)
returns table (
  project_id      text,
  tx_count        bigint,
  failed_tx_count bigint,
  usdc_gas        text,
  unique_users    bigint
)
language sql
stable
set search_path = public
as $$
  with win as (
    select d::date as wday
    from generate_series(
           (now() at time zone 'utc')::date - (p_days - 1),
           (now() at time zone 'utc')::date,
           interval '1 day') d
  ),
  pc as (
    select p.id as pid, lower(c.addr) as addr
    from projects p cross join lateral unnest(p.contracts) c(addr)
  ),
  act as (
    select pc.pid, sum(m.tx_count) as tx, sum(m.failed_tx_count) as failed, sum(m.usdc_gas_paid) as gas
    from pc cross join win
    join daily_contract_metrics m on m.day = win.wday and m.contract_address = pc.addr
    group by pc.pid
  ),
  usr as (
    select pc.pid, count(distinct u.address) as users
    from pc cross join win
    join daily_contract_users u on u.day = win.wday and u.contract_address = pc.addr
    group by pc.pid
  )
  select coalesce(act.pid, usr.pid),
         coalesce(act.tx, 0)::bigint,
         coalesce(act.failed, 0)::bigint,
         coalesce(act.gas, 0)::text,
         coalesce(usr.users, 0)::bigint
  from act full join usr on usr.pid = act.pid
$$;

-- Chain-wide window totals for network_stats. volume = ERC-20 transfer volume
-- of the 1:1-USD tokens only (USDC, USYC - same set as ingestion's
-- USD_PEGGED_1_TO_1); EURC is never added into a USD total. Gas is NOT
-- included in volume (native and ERC-20 views are one pool of funds).
create or replace function public.network_window_stats(p_days integer default 7)
returns table (
  total_tx        bigint,
  total_volume_usd text,
  unique_users    bigint,
  days_with_data  integer
)
language sql
stable
set search_path = public
as $$
  with ws as (select (now() at time zone 'utc')::date - (p_days - 1) as d0)
  select
    coalesce((select sum(tx_count) from daily_network_metrics, ws where day >= ws.d0), 0)::bigint,
    coalesce((select sum(volume) from daily_token_metrics, ws
              where day >= ws.d0
                and token_address in ('0x3600000000000000000000000000000000000000',
                                      '0x8a5d989bbb96929f689b0200f435f53da42bf490')), 0)::text,
    (select count(distinct address) from daily_active_addresses, ws where day >= ws.d0)::bigint,
    (select count(*) from daily_network_metrics, ws where day >= ws.d0)::integer
$$;

revoke execute on function public.project_window_metrics(integer) from public, anon, authenticated;
revoke execute on function public.network_window_stats(integer)  from public, anon, authenticated;
grant  execute on function public.project_window_metrics(integer) to service_role;
grant  execute on function public.network_window_stats(integer)  to service_role;
