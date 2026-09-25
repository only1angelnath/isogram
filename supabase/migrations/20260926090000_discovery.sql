-- Automatic contract/project discovery (docs/SCHEMA.md's original intent,
-- never built until now — see docs/HANDOVER.md section 5).
--
-- Every gas_events.contract_address ingestion sees that doesn't map to a
-- known projects.id gets tracked here instead of discarded. A background
-- classification step (ingestion/discovery.py, next) fills in category/
-- gecko_* once it has run; promotion to a real `projects` row happens only
-- once BOTH a call-frequency threshold is crossed AND classification has
-- assigned something better than 'unknown' (the hybrid approach) — pure
-- high call-count with no real signal stays 'needs_review' instead of
-- silently promoting as an unlabeled row.

create table if not exists discovered_contracts (
  contract_address   text primary key,        -- lowercase, matches gas_events.contract_address
  call_count          integer not null default 0,
  first_seen          timestamptz not null,
  last_seen           timestamptz not null,
  status              text not null default 'unclassified'
                        check (status in ('unclassified', 'needs_review', 'promoted', 'rejected')),
  -- classification results, filled in by ingestion/discovery.py
  category            text,                    -- 'token', 'dex', 'infra', 'unknown', ...
  gecko_symbol        text,
  gecko_name          text,
  gecko_score         numeric,                 -- GeckoTerminal gt_score, 0-100
  gecko_is_honeypot   text,                    -- GeckoTerminal is_honeypot: 'true' | 'false' | 'unknown'
  classified_at       timestamptz,
  -- set once promoted, links back to the real projects row
  promoted_project_id text references projects(id),
  promoted_at          timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create index if not exists discovered_contracts_status_idx on discovered_contracts (status);
create index if not exists discovered_contracts_call_count_idx on discovered_contracts (call_count);
create index if not exists discovered_contracts_last_seen_idx on discovered_contracts (last_seen);

-- Same public-read-only posture as every other table (see
-- supabase/migrations/20260925100000_enable_rls.sql) — this is data the
-- public dashboard/API can reasonably surface ("N candidates discovered,
-- M reviewed"), but only ingestion (service_role) writes it.
alter table discovered_contracts enable row level security;

create policy "public_read_only" on discovered_contracts
    for select to anon, authenticated using (true);
