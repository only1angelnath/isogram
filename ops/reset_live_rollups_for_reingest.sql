-- ops/reset_live_rollups_for_reingest.sql   (run in the Supabase SQL Editor)
--
-- WHY: until 2026-10-05 the worker counted USDC volume from the 6-decimal
-- ERC-20 log only, which misses plain native sends (measured: 74.4% of USDC
-- volume on 200 live blocks). The corrected worker uses Arc's system log. The
-- live days already ingested (2026-10-04 onward) used the old definition, and
-- raw rows no longer exist, so they are re-ingested from the first live block
-- instead of being patched. Days before 2026-10-04 (the 9/27-9/28 raw_backfill
-- rows) are NOT touched.
--
-- PRECONDITION (do not skip): the `ingestion-cron` workflow is DISABLED and no
-- run is in progress, and the corrected worker is already pushed. Otherwise an
-- old-code run can write between these statements.
--
-- Everything below is ONE transaction: all rows go and the checkpoint moves
-- back together, or nothing changes.

begin;

delete from daily_contract_users    where day >= '2026-10-04';
delete from daily_active_addresses  where day >= '2026-10-04';
delete from daily_contract_metrics  where day >= '2026-10-04';
delete from daily_token_metrics     where day >= '2026-10-04';
delete from daily_network_metrics   where day >= '2026-10-04';

-- 24297839 = the checkpoint set when live rollup ingestion first started
-- (first live block applied: 24297840).
update sync_state set last_block_number = 24297839, updated_at = now() where id = 1;

commit;

-- verify: only the two raw_backfill days remain, checkpoint rewound
select day, tx_count, source from daily_network_metrics order by day;
select last_block_number from sync_state;
