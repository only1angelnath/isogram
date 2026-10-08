-- ops/start_gap_backfill.sql   (run in the Supabase SQL Editor, AFTER the migration
-- 20261007000000_historical_gap_backfill.sql is applied)
--
-- Points the (single-row) historical backfill state at the hole left when the live
-- checkpoint was jumped on 2026-10-04:
--   first missing block  23225710  (right after the last raw-ingested block 23225709)
--   last missing block   24297839  (right before the first live rollup block 24297840)
-- Overwrites whatever the OLD (raw-row) backfill left in this table, which this replaces.

insert into historical_backfill_state (id, range_start, range_end, next_block)
values (1, 23225710, 24297839, 23225710)
on conflict (id) do update
  set range_start = excluded.range_start,
      range_end   = excluded.range_end,
      next_block  = excluded.next_block,
      updated_at  = now();

select range_start, range_end, next_block, (range_end - range_start + 1) as blocks_to_fill
from historical_backfill_state;
