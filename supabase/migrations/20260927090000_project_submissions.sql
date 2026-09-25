-- Project-owner self-submission ("list your project"), the third
-- classification path alongside GeckoTerminal auto-classification and
-- admin manual override (see ingestion/admin_tools.py).
--
-- Deliberately NOT anon-writable via Supabase's REST layer — that would
-- reopen the exact class of gap supabase/migrations/20260925100000_enable_rls.sql
-- closed. Submissions go through api/routes/submit.py instead, which
-- validates input server-side and writes with service_role. RLS here is
-- fully closed to anon/authenticated (no policies at all) — every access
-- path is the API or an admin with the service key.

create table if not exists project_submissions (
  id                  bigserial primary key,
  contract_address    text not null,           -- lowercase
  proposed_name       text,
  proposed_category   text,
  socials             jsonb default '{}',
  submitter_contact    text,                    -- email/telegram/twitter, optional
  note                text,                     -- free-text from the submitter
  status              text not null default 'pending'
                        check (status in ('pending', 'approved', 'rejected')),
  reviewed_at         timestamptz,
  reviewer_note       text,
  created_at          timestamptz not null default now()
);

create index if not exists project_submissions_status_idx on project_submissions (status);
create index if not exists project_submissions_contract_address_idx on project_submissions (contract_address);

alter table project_submissions enable row level security;
-- No policies added on purpose: RLS with zero policies means nobody using
-- the anon or authenticated role can read or write this table at all.
-- Only service_role (which bypasses RLS) can touch it — that's the API
-- and admin tooling, never a direct public request.
