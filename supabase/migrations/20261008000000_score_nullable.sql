-- 20261008000000_score_nullable.sql
--
-- ADR-004: only DeFi protocols are scored. Launchpads, infrastructure, tokens and
-- stablecoins get score = NULL ("not applicable"), never 0 - a 0 would read as "scored, and
-- worst". project_scores.score was NOT NULL, so scoring would fail on the first non-DeFi row.
-- tvl_usd was already nullable (also NULL for non-DeFi now: "not applicable").
--
-- Apply BEFORE deploying the new scoring job. Safe to apply early: the current job always
-- writes a score, and the API already treats a null score as "no score" (badge, rankings).

alter table public.project_scores alter column score drop not null;
