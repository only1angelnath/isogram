-- 20261005020000_api_metrics_layer.sql
--
-- Read layer for the new metrics endpoints + a fix for a latent API bug.
--
-- BUG FIXED: api/db.fetch_all_latest_scores() read EVERY project_scores row
-- (one per project per scoring run) with no pagination. At ~160 projects and a
-- run every 4 h that passes PostgREST's silent 1000-row cap within a day, after
-- which /projects, /scores/top etc. would serve arbitrary, stale scores with no
-- error. latest_project_scores returns exactly one row per project instead.
--
-- The functions below are read-only and return AGGREGATES ONLY (never
-- addresses). They are SECURITY DEFINER so the API can call them with the anon
-- key: daily_contract_users has no anon policy on purpose (it holds sender
-- addresses), but distinct COUNTS of it are public-safe.

create index if not exists project_scores_project_computed_idx
  on public.project_scores (project_id, computed_at desc);

create or replace view public.latest_project_scores
with (security_invoker = true) as
select distinct on (project_id)
       project_id, score, tvl_usd, usdc_gas_7d, unique_users_7d,
       tx_count_7d, failed_tx_7d, computed_at
from public.project_scores
order by project_id, computed_at desc;

grant select on public.latest_project_scores to anon, authenticated, service_role;

-- Top contracts by USDC gas over the last p_days UTC days (today included),
-- attributed to a tracked project when one claims the contract. gas_share is
-- relative to ALL gas paid on the network in the same window.
create or replace function public.top_contracts(p_days integer default 7, p_limit integer default 20)
returns table (
  contract_address text,
  project_id       text,
  project_name     text,
  category         text,
  tx_count         bigint,
  failed_tx_count  bigint,
  usdc_gas         text,
  gas_share        numeric
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
  )
  select a.addr, p.id, p.name, p.category,
         a.tx::bigint, a.failed::bigint, a.gas::text,
         case when tot.gas > 0 then round(a.gas / tot.gas, 6) end
  from agg a
  cross join tot
  left join lateral (
    select pr.id, pr.name, pr.category from projects pr where a.addr = any (pr.contracts) limit 1
  ) p on true
  order by a.gas desc, a.addr
  limit least(greatest(p_limit, 1), 100)
$$;

-- One project's daily series. Only days the pipeline has data for (rows in
-- daily_network_metrics) are returned, so a real zero is a zero and a day the
-- pipeline did not cover (e.g. 2026-09-29..10-03) is absent, never faked as 0.
-- unique_users covers contracts that were TRACKED at ingestion time.
create or replace function public.project_daily_metrics(p_project_id text, p_days integer default 30)
returns table (
  day             date,
  tx_count        bigint,
  failed_tx_count bigint,
  usdc_gas        text,
  unique_users    bigint
)
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
    select m.day as aday, sum(m.tx_count) as tx, sum(m.failed_tx_count) as failed, sum(m.usdc_gas_paid) as gas
    from daily_contract_metrics m join pc on m.contract_address = pc.addr
    group by m.day
  ),
  usr as (
    select u.day as uday, count(distinct u.address) as users
    from daily_contract_users u join pc on u.contract_address = pc.addr
    group by u.day
  )
  select cal.cday,
         coalesce(act.tx, 0)::bigint, coalesce(act.failed, 0)::bigint,
         coalesce(act.gas, 0)::text, coalesce(usr.users, 0)::bigint
  from cal
  left join act on act.aday = cal.cday
  left join usr on usr.uday = cal.cday
  order by cal.cday
$$;

revoke execute on function public.top_contracts(integer, integer) from public, anon, authenticated;
revoke execute on function public.project_daily_metrics(text, integer) from public, anon, authenticated;
grant  execute on function public.top_contracts(integer, integer) to anon, authenticated, service_role;
grant  execute on function public.project_daily_metrics(text, integer) to anon, authenticated, service_role;
