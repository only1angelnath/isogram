-- Seed the Uniswap v4 PoolManager as a tracked project.
--
-- Address confirmed against multiple independent sources (Uniswap's own
-- UniswapX playbook repo, a Uniswap hooklist PR, and Bitquery's Arc mainnet
-- docs), all agreeing on the same address for chain 5042 and describing it
-- as verified live code (~24KB, not a placeholder/squatter contract — see
-- docs/SCHEMA.md for the cross-reference). This was referenced in planning
-- since day one but never actually pinned down until now (see
-- docs/IMPLEMENTATION_PLAN.md Week 2 item 5, docs/SCHEMA.md project seed list).

insert into projects (id, name, contracts, category, socials)
values (
  'uniswap-v4',
  'Uniswap v4',
  array['0x8366a39cc670b4001a1121b8f6a443a643e40951'],
  'dex',
  '{"website": "https://uniswap.org"}'::jsonb
)
on conflict (id) do update
  set contracts = excluded.contracts;
