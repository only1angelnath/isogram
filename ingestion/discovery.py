"""
ingestion/discovery.py

Automatic contract/project discovery — the mechanism docs/SCHEMA.md
described from day one but never built (see docs/HANDOVER.md section 5).

Flow, run once per ingestion cycle (call run_discovery() after the normal
worker.py block-processing pass):

1. upsert_unmapped_contracts() — every gas_events.contract_address with no
   project_id gets an upsert into discovered_contracts (call_count,
   first_seen, last_seen bumped each run).
2. classify_candidates() — for rows at or above CALL_COUNT_THRESHOLD that
   are still 'unclassified', run the classification pipeline and record
   the result, then move to 'needs_review' EITHER WAY (see 2026-09-30
   note below) — category filled in if a real signal was found, or
   category=NULL if every source was tried and none matched.
3. promote_ready_candidates() — status='needs_review' rows that have a
   non-null category get inserted into projects and marked 'promoted'.
   This is the hybrid gate from docs/HANDOVER.md section 5: call-count
   threshold AND real classification, not either alone. Rows that reached
   'needs_review' with category=NULL are exactly the manual-review queue
   docs/AUDIT.md's admin routes are for — a human sets the category via
   the admin panel, and the next run's promote_ready_candidates() picks
   them up automatically once that happens.

Rows below CALL_COUNT_THRESHOLD are left 'unclassified' and simply keep
accumulating call_count on every run until they either cross the
threshold or the chain shows they're one-off noise.

CHANGED 2026-09-30: a real check against ~1,100 accumulated candidates
showed the ORIGINAL bug in this file — candidates that failed
classification stayed status='unclassified' forever, meaning (a) they were
silently re-classified (and re-billed against API quota) on every single
ingestion cycle indefinitely, and (b) they never actually reached the admin
manual-review queue despite the module docstring always having described
that as the intended fallback. Fixed: classify_candidates() now always
transitions a checked candidate to 'needs_review' (with category=NULL on a
miss), so it's checked exactly once automatically and then either
auto-promotes or waits for a human.

Also added Dexscreener as a second, independent, keyless classification
source alongside CoinGecko/GeckoTerminal (which are the same underlying
onchain data — CoinGecko acquired GeckoTerminal — just paid vs. free tier;
this now falls back to the free public endpoint when COINGECKO_PRO_API_KEY
isn't set, instead of skipping classification entirely). Arkham was
considered and dropped: paid-only, and no confirmed Arc coverage, unlike
CoinGecko/GeckoTerminal/Dexscreener which reportedly do have real Arc data
— confirmed directly: GeckoTerminal's network ID for Arc is literally
"arc" (verified against /onchain/networks with a real key), so a wrong
network slug was ruled out as the cause of the 0% hit rate seen on the
first 21 needs_review candidates.

CHANGED 2026-09-30 (again): manual inspection of those 21 candidates on
explorer.arc.io found some are plain EOAs (wallet addresses), not
contracts at all — upsert_unmapped_contracts() pulls every
gas_events.to_address with no project_id indiscriminately, contract or
not. No classification source can ever find a token/pool/entity for a
wallet address, so these were guaranteed misses regardless of which
external APIs get added. Fixed: classify_candidates() now checks
eth_getCode first (reusing worker.py's RPC pool/retry/sticky-endpoint
machinery directly — discovery.py already lives in ingestion/ and shares
its requirements.txt/secrets, unlike scoring/'s deliberate separation) and
marks an EOA 'rejected' immediately, without spending any external API
calls or ever surfacing it in the manual-review queue.

CHANGED 2026-10-01: added explorer.arc.io's own Blockscout API as a THIRD
classification source, tried first (before CoinGecko/Dexscreener) — it
turned out to have far better real-world coverage for exactly the
contracts the token-pool indexers structurally can't see: verified
periphery/infra contracts (routers, quoters, a proxy to "IntentSettler")
and proxy-implementation names that reveal templated launchpad clone
tokens (e.g. "ArgusV4LaunchToken7"). New category "launchpad" keeps
mass-produced clone tokens from a factory visually/structurally separate
from independently-built projects; new category "dex" catches verified
DEX-infra contracts by name keyword (_DEX_INFRA_NAME_KEYWORDS), gated
behind is_verified=true. Needed a browser-like User-Agent — Cloudflare
(fronting explorer.arc.io) silently blocks requests' default UA.
"""

import os
import sys
from datetime import datetime, timezone

import requests
from supabase import create_client
from web3 import Web3

from worker import _StickyPoolIndex, _call_on_pool, get_web3_pool

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
# Optional. If set, uses CoinGecko's paid pro-api (higher rate limit). If
# unset, falls back to the free public api.coingecko.com onchain endpoint
# (same underlying GeckoTerminal data, just rate-limited) — so
# classification still works with zero cost/setup, just more slowly at
# higher candidate volume.
COINGECKO_API_KEY = os.environ.get("COINGECKO_PRO_API_KEY")

# Tune as more days of real gas_events accumulate (see the distribution
# query in docs/HANDOVER.md-adjacent notes — no sharp cliff yet at 9 days
# of mainnet activity, so this is deliberately conservative and leans on
# classify_one() to do the real filtering, not this number alone).
CALL_COUNT_THRESHOLD = 15

# Canonical, deterministically-deployed infra contracts that appear at
# the same address across most EVM chains. These are shared plumbing,
# not "a project someone built" — classify them immediately without
# spending an API call on them, and never surface them as if they were a
# discovered Arc-native project.
KNOWN_INFRA_CONTRACTS = {
    "0x000000000022d473030f116ddee9f6b43ac78ba3": "Uniswap Permit2",
    "0x0000000071727de22e5e9d8baf0edac6f37da032": "ERC-4337 EntryPoint v0.7",
}

GECKOTERMINAL_PRO_URL = (
    "https://pro-api.coingecko.com/api/v3/onchain/networks/arc/tokens/{address}/info"
)
GECKOTERMINAL_FREE_URL = (
    "https://api.coingecko.com/api/v3/onchain/networks/arc/tokens/{address}/info"
)
# Free, keyless, multi-chain pair index — a second, independent source that
# might have a given Arc pair indexed even if CoinGecko/GeckoTerminal
# doesn't (or vice versa).
DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"

# Added 2026-10-01: explorer.arc.io's own Blockscout API. Confirmed live to
# have FAR better coverage than CoinGecko/GeckoTerminal or Dexscreener for
# exactly the contracts those two miss — verified contract names (incl.
# proxy implementations), which catches periphery/infra contracts
# (routers, quoters, settlers) that pure token-pool indexers structurally
# can never classify (they only see priced ERC-20s with liquidity, not
# arbitrary verified contracts). Tried FIRST, before the token-only
# sources, based on this observed efficacy — on the first real batch of 23
# candidates, Blockscout correctly identified several (UniversalRouter,
# SwapRouter02, a proxy to IntentSettler, an ArgusV4LaunchToken* clone)
# that both other sources missed entirely.
#
# Cloudflare fronts this domain and silently blocks requests' default
# User-Agent ("python-requests/x.x") — confirmed live: identical requests
# succeeded with a browser-like UA and returned nothing at all without one,
# across all 23 test addresses uniformly. _EXPLORER_HEADERS below is not
# optional window-dressing, it's required for this to work at all.
EXPLORER_ADDRESS_INFO_URL = "https://explorer.arc.io/api/v2/addresses/{address}"
_EXPLORER_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

# DeFiLlama-style category taxonomy (2026-10-02), shared across every
# classification source (Blockscout verified names, CoinGecko/GeckoTerminal
# token metadata, Dexscreener pairs) instead of each one hardcoding its own
# generic "token"/"infra"/"dex". One category column still covers both
# "protocol type" (dex, bridge, oracle, lending...) and "token type"
# (stablecoin, meme, governance...) — a discovered contract becomes exactly
# one projects row either way, so one richer vocabulary does the job
# without a schema change.
#
# Matched via substring, case-insensitive, against whatever name/symbol a
# source actually returned — deliberately keyword-based, not an address
# list like KNOWN_INFRA_CONTRACTS, since these are generic naming
# conventions, not addresses we're independently vouching for one at a
# time. The DEX keyword match additionally requires is_verified=true when
# checked against Blockscout (see _classify_from_blockscout) so a scam
# contract can't just name itself "FooRouter" to get auto-categorized —
# CoinGecko/Dexscreener hits are already gated by being real indexed
# tokens/pairs, so no separate verified-flag exists to check there.
#
# Order matters: first matching category wins, checked top to bottom, so
# more specific categories are listed before more generic ones (e.g.
# "liquid-staking" before a bare "staking" catch-all would be, if one
# existed — kept this list to patterns actually worth distinguishing for
# an Arc-stage chain rather than DeFiLlama's full ~30-category breadth).
_CATEGORY_NAME_KEYWORDS = (
    ("bridge", ("bridge", "bridged", "portal")),
    ("oracle", ("oracle", "pricefeed", "price-feed")),
    ("liquid-staking", ("liquidstaking", "liquid staking", "lst", "steth", "lsteth")),
    ("lending", ("lend", "cdp", "vault", "comptroller")),
    ("yield", ("yield", "farm", "harvest")),
    ("dex", ("router", "quoter", "swap", "poolmanager", "positionmanager", "settler", "aggregator", "universalrouter")),
    ("governance", ("governance", "dao", "timelock", "votingescrow", "gauge")),
    ("stablecoin", ("usd", "stable", "dollar")),
    ("wrapped", ("wrapped", "bridged weth", "weth")),
    ("meme", ("meme", "doge", "shib", "pepe", "inu", "moon", "elon")),
)


def _infer_category(name: str | None, symbol: str | None, default: str = "token") -> str:
    """
    Shared DeFiLlama-style category inference: check name and symbol
    (lowercased) against _CATEGORY_NAME_KEYWORDS in order, return the first
    match, or `default` if nothing matches. Used by every classification
    source so a token named e.g. "USD Coin Bridge" gets the same category
    regardless of whether CoinGecko, Dexscreener, or Blockscout was the
    source that found it.
    """
    haystack = f"{name or ''} {symbol or ''}".lower()
    for category, keywords in _CATEGORY_NAME_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return category
    return default


def _client():
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def upsert_unmapped_contracts(db=None) -> int:
    """Pull distinct unmapped contract_addresses from gas_events and
    upsert call_count/first_seen/last_seen into discovered_contracts.
    Returns the number of distinct contracts touched this run."""
    db = db or _client()
    now = datetime.now(timezone.utc).isoformat()

    resp = (
        db.table("gas_events")
        .select("contract_address, ts")
        .is_("project_id", "null")
        .execute()
    )
    rows = resp.data or []

    agg = {}
    for row in rows:
        addr = row["contract_address"].lower()
        ts = row["ts"]
        entry = agg.setdefault(addr, {"call_count": 0, "first_seen": ts, "last_seen": ts})
        entry["call_count"] += 1
        if ts < entry["first_seen"]:
            entry["first_seen"] = ts
        if ts > entry["last_seen"]:
            entry["last_seen"] = ts

    for addr, entry in agg.items():
        db.table("discovered_contracts").upsert(
            {
                "contract_address": addr,
                "call_count": entry["call_count"],
                "first_seen": entry["first_seen"],
                "last_seen": entry["last_seen"],
                "updated_at": now,
            },
            on_conflict="contract_address",
        ).execute()

    return len(agg)


GECKOTERMINAL_TRENDING_PRO_URL = (
    "https://pro-api.coingecko.com/api/v3/onchain/networks/arc/trending_pools"
    "?page={page}&include=base_token,quote_token"
)
GECKOTERMINAL_TRENDING_FREE_URL = (
    "https://api.coingecko.com/api/v3/onchain/networks/arc/trending_pools"
    "?page={page}&include=base_token,quote_token"
)
# NOTE (2026-10-03): confirmed live that GeckoTerminal's JSON:API-style
# response ONLY populates the top-level "included" array when explicitly
# asked for it via ?include=... — without this param, included is simply
# absent, which the original version of this code misread as "no more
# pages" and broke out on page 1 every time (0 seeded). Don't drop this
# param "to simplify the URL" without re-verifying the response shape.
# How many pages of trending pools to pull per discovery run. Cheap and
# idempotent to repeat every cycle (just bumps call_count/timestamps on
# already-known candidates), so no need to track "already seen" state —
# capped to keep each run's API usage bounded.
GECKOTERMINAL_TRENDING_PAGES = int(os.environ.get("GECKOTERMINAL_TRENDING_PAGES", "3"))


def fetch_trending_pool_candidates(db=None) -> int:
    """
    Proactively seed discovered_contracts from GeckoTerminal's trending
    Arc pools, instead of relying solely on organic gas_events volume
    crossing CALL_COUNT_THRESHOLD. A pool that's genuinely trending on
    GeckoTerminal is real, externally-validated activity — worth fast-
    tracking into the classification pipeline rather than waiting for our
    own ingestion to independently accumulate enough call_count on the
    same contract.

    Every token address found this way still goes through the exact same
    discovered_contracts -> classify_candidates -> promote_ready_candidates
    pipeline as organically-discovered contracts — same EOA filter, same
    classification sources, same collision protection against overwriting
    an existing project (see promote_ready_candidates' 2026-10-02 fix).
    This function only ever upserts into discovered_contracts; it never
    touches projects directly, so none of today's safety work is bypassed.

    Sets call_count to CALL_COUNT_THRESHOLD directly (not accumulated
    organically) so a trending pool's tokens are eligible for
    classification on the very next classify_candidates() pass — clearly
    a synthetic value, not a real observed call count, which is why this
    is kept as a separate function rather than folded into
    upsert_unmapped_contracts() (which reflects real gas_events activity).
    Returns the number of distinct token addresses touched this run.
    """
    db = db or _client()
    now_iso = datetime.now(timezone.utc).isoformat()
    addresses: set[str] = set()

    for page in range(1, GECKOTERMINAL_TRENDING_PAGES + 1):
        try:
            if COINGECKO_API_KEY:
                resp = requests.get(
                    GECKOTERMINAL_TRENDING_PRO_URL.format(page=page),
                    headers={"x-cg-pro-api-key": COINGECKO_API_KEY},
                    timeout=10,
                )
            else:
                resp = requests.get(
                    GECKOTERMINAL_TRENDING_FREE_URL.format(page=page),
                    timeout=10,
                )
            if resp.status_code != 200:
                print(
                    f"discovery: trending_pools page {page} returned {resp.status_code}, stopping "
                    f"(using {'pro' if COINGECKO_API_KEY else 'free'} endpoint): {resp.text[:200]}",
                    file=sys.stderr,
                )
                break
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"discovery: trending_pools page {page} request failed: {exc}", file=sys.stderr)
            break

        included = payload.get("included") or []
        if not included:
            break  # no more pages / nothing returned

        for item in included:
            if item.get("type") != "token":
                continue
            addr = (item.get("attributes") or {}).get("address")
            if addr:
                addresses.add(addr.lower())

    if not addresses:
        return 0

    # Fetch existing rows for these addresses first so this never regresses
    # a real, organically-accumulated call_count downward, and never
    # overwrites a genuinely earlier first_seen with "now".
    existing_resp = (
        db.table("discovered_contracts")
        .select("contract_address, call_count, first_seen")
        .in_("contract_address", list(addresses))
        .execute()
    )
    existing_by_addr = {row["contract_address"]: row for row in (existing_resp.data or [])}

    for addr in addresses:
        existing = existing_by_addr.get(addr)
        db.table("discovered_contracts").upsert(
            {
                "contract_address": addr,
                "call_count": max(CALL_COUNT_THRESHOLD, (existing or {}).get("call_count", 0)),
                "first_seen": (existing or {}).get("first_seen") or now_iso,
                "last_seen": now_iso,
                "updated_at": now_iso,
            },
            on_conflict="contract_address",
        ).execute()

    return len(addresses)


def _gecko_token_info(address: str) -> dict | None:
    """
    Query CoinGecko/GeckoTerminal's onchain token-info endpoint — paid
    pro-api if COINGECKO_PRO_API_KEY is set (higher rate limit), else the
    free public endpoint (same data, keyless, more rate-limited). Returns
    None on 404 (not indexed), any non-200, or any request failure; never
    raises, since a classification miss should just leave the candidate
    for the next source (or manual review), not break the ingestion run.
    """
    try:
        if COINGECKO_API_KEY:
            resp = requests.get(
                GECKOTERMINAL_PRO_URL.format(address=address),
                headers={"x-cg-pro-api-key": COINGECKO_API_KEY},
                timeout=10,
            )
        else:
            resp = requests.get(
                GECKOTERMINAL_FREE_URL.format(address=address),
                timeout=10,
            )
        if resp.status_code != 200:
            return None
        return resp.json().get("data", {}).get("attributes")
    except requests.RequestException:
        return None


def _dexscreener_token_info(address: str) -> dict | None:
    """
    Query Dexscreener's free/keyless token endpoint. Returns the first
    pair whose chainId looks like Arc, or None if nothing matches (address
    not traded anywhere Dexscreener indexes, or the request fails). Never
    raises — same fail-safe contract as _gecko_token_info().

    NOTE: Dexscreener's exact chainId slug for Arc hasn't been confirmed
    against a live response yet — the check below tries a few plausible
    values. If none match the real slug, this always returns None (no
    crash, just contributes nothing). The first time this actually returns
    a nonempty `pairs` list, log/inspect the real chainId value and narrow
    this set to just that.
    """
    try:
        resp = requests.get(
            DEXSCREENER_TOKEN_URL.format(address=address),
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        pairs = resp.json().get("pairs") or []
        plausible_arc_slugs = {"arc", "arc-network", "arcmainnet", "circle-arc"}
        for pair in pairs:
            if (pair.get("chainId") or "").lower() in plausible_arc_slugs:
                return pair
        return None
    except requests.RequestException:
        return None


def _is_eoa(pool: list, sticky: "_StickyPoolIndex", address: str) -> bool:
    """
    True if `address` has no contract bytecode (a plain wallet), via
    eth_getCode. Empty result ("0x" / b"") means EOA. Reuses worker.py's
    _call_on_pool so this gets the same retry/backoff and sticky-endpoint
    behavior as every other RPC call in this codebase, not a separate
    ad-hoc implementation.

    web3.py validates addresses passed to eth_* calls as checksummed
    (EIP-55) and raises InvalidAddress otherwise — confirmed live
    2026-09-30, same issue scoring/tvl.py hit on eth_call. contract_address
    is stored lowercase throughout this codebase (ingestion/worker.py,
    discovered_contracts), so it must be checksummed here, not upstream.
    """
    checksummed = Web3.to_checksum_address(address)
    code = _call_on_pool(pool, sticky, "get_code", checksummed)
    return not code or code == b"" or code.hex() in ("", "0x")


def _blockscout_address_info(address: str) -> dict | None:
    """
    Query explorer.arc.io's Blockscout API. Returns the raw address-info
    dict on success, or None on any non-200/failure — same fail-safe
    contract as every other source here. Requires _EXPLORER_HEADERS'
    browser User-Agent (see its comment above) or Cloudflare silently
    blocks the request.
    """
    try:
        resp = requests.get(
            EXPLORER_ADDRESS_INFO_URL.format(address=address),
            headers=_EXPLORER_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except requests.RequestException:
        return None


def _classify_from_blockscout(info: dict) -> dict | None:
    """
    Turn a Blockscout address-info response into a classification result,
    or None if it doesn't give us anything usable (unverified AND not a
    recognized token — in which case the caller falls through to the
    token-pool sources, which occasionally catch something Blockscout's
    verification-based view misses).

    Category logic, in priority order:
    1. Token behind an EIP-1167 (or other) proxy whose IMPLEMENTATION name
       suggests a templated launchpad clone (e.g. "ArgusV4LaunchToken7")
       -> category "launchpad", ALWAYS — this overrides _infer_category
       even if the token's own name/symbol would otherwise match e.g.
       "meme" or "stablecoin", because launchpad-clone provenance is a
       more useful signal for this dashboard than the token's surface
       branding. Keeps mass-produced clone tokens visually and
       structurally separate from independently-built projects — they're
       real activity, but a different kind than a project someone wrote
       from scratch, and lumping hundreds of near-identical clones in with
       genuine dApps would dilute "what's actually live on Arc" for a
       grant reviewer.
    2. Any other recognized ERC-20 token -> category inferred from its
       name/symbol via the shared DeFiLlama-style taxonomy
       (_infer_category) — "stablecoin", "meme", "governance", "wrapped",
       etc., falling back to generic "token" if nothing matches.
    3. Verified contract (not a token) -> category inferred from its own
       verified name via the same taxonomy — catches "dex" (routers,
       quoters...), "bridge", "oracle", "lending", "yield", "governance"
       equally, not just DEX as before. Falls back to generic "infra" if
       verified but nothing matches (same bucket Permit2/EntryPoint use).
    4. Unverified, not a recognized token -> None (let the caller try the
       remaining sources / fall through to manual review).
    """
    is_verified = info.get("is_verified", False)
    name = info.get("name")
    token = info.get("token")
    implementations = info.get("implementations") or []
    impl_names = " ".join((i.get("name") or "") for i in implementations)

    if token:
        symbol = token.get("symbol")
        token_name = token.get("name")
        category = "launchpad" if "launch" in impl_names.lower() else _infer_category(token_name, symbol)
        return {
            "category": category,
            "gecko_symbol": symbol,
            "gecko_name": token_name,
            "gecko_score": None,
            "gecko_is_honeypot": None,
        }

    if is_verified and name:
        category = _infer_category(name, None, default="infra")
        return {
            "category": category,
            "gecko_symbol": None,
            "gecko_name": name,
            "gecko_score": None,
            "gecko_is_honeypot": None,
        }

    return None


def classify_one(address: str) -> dict:
    """
    Classify a single candidate contract, trying each source in order and
    stopping at the first hit. Returns a dict with
    category/gecko_symbol/gecko_name/gecko_score/gecko_is_honeypot,
    category=None if NO source found a signal (this row then goes to
    needs_review for manual admin classification — see
    classify_candidates()).

    Order: known infra (free, instant, no API call) -> Blockscout
    (explorer.arc.io — verified-name + proxy-implementation data; tried
    first based on observed efficacy, see EXPLORER_ADDRESS_INFO_URL's
    comment) -> CoinGecko/GeckoTerminal onchain (token + pool data) ->
    Dexscreener (independent pool index).
    """
    address = address.lower()

    if address in KNOWN_INFRA_CONTRACTS:
        return {
            "category": "infra",
            "gecko_symbol": None,
            "gecko_name": KNOWN_INFRA_CONTRACTS[address],
            "gecko_score": None,
            "gecko_is_honeypot": None,
        }

    blockscout_info = _blockscout_address_info(address)
    if blockscout_info:
        result = _classify_from_blockscout(blockscout_info)
        if result:
            return result

    gecko_attrs = _gecko_token_info(address)
    if gecko_attrs:
        symbol = gecko_attrs.get("symbol")
        name = gecko_attrs.get("name")
        return {
            "category": _infer_category(name, symbol),
            "gecko_symbol": symbol,
            "gecko_name": name,
            "gecko_score": gecko_attrs.get("gt_score"),
            "gecko_is_honeypot": str(gecko_attrs.get("is_honeypot")),
        }

    dex_pair = _dexscreener_token_info(address)
    if dex_pair:
        base = dex_pair.get("baseToken") or {}
        symbol = base.get("symbol")
        name = base.get("name")
        return {
            "category": _infer_category(name, symbol),
            "gecko_symbol": symbol,
            "gecko_name": name,
            "gecko_score": None,
            "gecko_is_honeypot": None,
        }

    # No signal from any source. TODO: event-topic heuristic here (does it
    # look like a DEX pool from its Transfer/Swap event shape in
    # gas_events/token_flows?) — not yet implemented. Until then this
    # candidate goes to needs_review with category=NULL — the manual admin
    # review queue (docs/AUDIT.md) is the real fallback, not another
    # automated source.
    return {
        "category": None,
        "gecko_symbol": None,
        "gecko_name": None,
        "gecko_score": None,
        "gecko_is_honeypot": None,
    }


def classify_candidates(db=None) -> int:
    """
    Classify every 'unclassified' candidate at or above
    CALL_COUNT_THRESHOLD. Returns the number classified this run.

    Every candidate checked here moves to a terminal state regardless of
    outcome (fixed 2026-09-30 — see module docstring): 'rejected' if it's a
    plain EOA (no bytecode — checked first, before spending any external
    API call), else 'needs_review' with category filled in on a
    classification hit or NULL on a miss. A miss means "checked once, no
    automated source found anything" — it's the manual-review queue's job
    from here, not another automatic re-check next run.
    """
    db = db or _client()
    now = datetime.now(timezone.utc).isoformat()
    pool = get_web3_pool()
    sticky = _StickyPoolIndex()

    resp = (
        db.table("discovered_contracts")
        .select("contract_address")
        .eq("status", "unclassified")
        .gte("call_count", CALL_COUNT_THRESHOLD)
        .execute()
    )
    candidates = resp.data or []

    classified = 0
    for row in candidates:
        addr = row["contract_address"]

        if _is_eoa(pool, sticky, addr):
            db.table("discovered_contracts").update(
                {
                    "status": "rejected",
                    "classified_at": now,
                    "updated_at": now,
                }
            ).eq("contract_address", addr).execute()
            classified += 1
            continue

        result = classify_one(addr)
        db.table("discovered_contracts").update(
            {
                **result,
                "status": "needs_review",
                "classified_at": now,
                "updated_at": now,
            }
        ).eq("contract_address", addr).execute()
        classified += 1

    return classified


def promote_ready_candidates(db=None) -> int:
    """Promote 'needs_review' candidates with a non-null category into
    projects. The hybrid gate: call_count >= CALL_COUNT_THRESHOLD
    (already true to have reached 'needs_review') AND category is set
    (real classification signal, not just volume). Returns the number
    promoted this run.

    CHANGED 2026-10-02: a discovered contract's slug ("usyc", from a
    classification source returning symbol "USYC") silently collided with
    the real, manually-seeded USYC project — upsert(on_conflict="id")
    overwrote its name/category/contracts with an impostor's data, no
    error, no warning. This is exactly the squatting/impersonation risk
    docs/SCHEMA.md already flagged for well-known addresses, just hitting
    name collision instead of address collision. Fixed: promotion now
    checks for an existing project at that id FIRST. If one exists with a
    DIFFERENT contract address, this is treated as a probable impersonator
    — the candidate is marked 'rejected' (not promoted, not left stuck in
    needs_review either) and the real project is never touched. A
    collision where the contract address actually matches (the same
    project rediscovering itself, e.g. after a schema change) is allowed
    through as a genuine update.
    """
    db = db or _client()
    now = datetime.now(timezone.utc).isoformat()

    resp = (
        db.table("discovered_contracts")
        .select("*")
        .eq("status", "needs_review")
        .not_.is_("category", "null")
        .execute()
    )
    ready = resp.data or []

    promoted = 0
    collisions_rejected = 0
    for row in ready:
        addr = row["contract_address"]
        slug_source = (row.get("gecko_symbol") or row.get("gecko_name") or addr).lower()
        project_id = "".join(c if c.isalnum() else "-" for c in slug_source).strip("-")

        existing = db.table("projects").select("id, contracts").eq("id", project_id).execute()
        if existing.data:
            existing_contracts = [c.lower() for c in (existing.data[0].get("contracts") or [])]
            if addr.lower() not in existing_contracts:
                # Slug collision with a DIFFERENT contract than the one
                # already tracked under this id — do not overwrite. Likely
                # an impersonator (same name/symbol as a real project, or
                # a slug coincidence with an unrelated already-promoted
                # discovery). Reject rather than silently corrupt the
                # existing project or sit stuck in needs_review forever.
                db.table("discovered_contracts").update(
                    {
                        "status": "rejected",
                        "updated_at": now,
                    }
                ).eq("contract_address", addr).execute()
                print(
                    f"discovery: REJECTED {addr} — slug '{project_id}' already used by a "
                    f"different contract ({existing_contracts}); likely impersonation/collision, "
                    f"not overwriting the existing project."
                )
                collisions_rejected += 1
                continue
            # Same contract already tracked under this id — fall through
            # to the upsert below as a legitimate refresh, not a collision.

        db.table("projects").upsert(
            {
                "id": project_id,
                "name": row.get("gecko_name") or row.get("gecko_symbol") or addr,
                "contracts": [addr],
                "category": row["category"],
                "socials": {},
            },
            on_conflict="id",
        ).execute()

        db.table("discovered_contracts").update(
            {
                "status": "promoted",
                "promoted_project_id": project_id,
                "promoted_at": now,
                "updated_at": now,
            }
        ).eq("contract_address", addr).execute()
        promoted += 1

    if collisions_rejected:
        print(f"discovery: {collisions_rejected} slug collision(s) rejected this run — see REJECTED lines above.")

    return promoted


def run_discovery() -> dict:
    """
    Full discovery pass: seed (organic + proactive) -> classify -> promote.
    Call once per ingestion cycle, after the normal block-processing pass.

    Two independent seeding paths feed the same discovered_contracts table:
    organic (upsert_unmapped_contracts — real gas_events activity) and
    proactive (fetch_trending_pool_candidates — GeckoTerminal's trending
    Arc pools, added 2026-10-02 so real, externally-validated activity
    doesn't have to wait for our own ingestion to independently rack up
    enough call_count on the same contract). Both funnel into the exact
    same classify/promote pipeline, so every safety mechanism (EOA
    filtering, collision-protected promotion) applies equally to either
    source.
    """
    db = _client()
    touched = upsert_unmapped_contracts(db)
    trending_seeded = fetch_trending_pool_candidates(db)
    classified = classify_candidates(db)
    promoted = promote_ready_candidates(db)
    return {
        "touched": touched,
        "trending_seeded": trending_seeded,
        "classified": classified,
        "promoted": promoted,
    }


if __name__ == "__main__":
    result = run_discovery()
    print(f"Discovery run: {result['touched']} contracts touched, "
          f"{result['trending_seeded']} seeded from trending pools, "
          f"{result['classified']} classified, {result['promoted']} promoted.")
