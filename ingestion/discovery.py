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
   the result. Two outcomes:
     - real signal found (known infra, or a GeckoTerminal-indexed token
       with a pool) -> status='needs_review', category/gecko_* filled in
     - no real signal -> status stays 'unclassified' (or moves to
       'needs_review' with category=NULL if it's genuinely been reviewed
       and found wanting — see classify_one())
3. promote_ready_candidates() — status='needs_review' rows that have a
   non-null category get inserted into projects and marked 'promoted'.
   This is the hybrid gate from docs/HANDOVER.md section 5: call-count
   threshold AND real classification, not either alone.

Rows below CALL_COUNT_THRESHOLD are left 'unclassified' and simply keep
accumulating call_count on every run until they either cross the
threshold or the chain shows they're one-off noise.
"""

import os
from datetime import datetime, timezone

import requests
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
COINGECKO_API_KEY = os.environ.get("COINGECKO_PRO_API_KEY")

# Tune as more days of real gas_events accumulate (see the distribution
# query in docs/HANDOVER.md-adjacent notes — no sharp cliff yet at 9 days
# of mainnet activity, so this is deliberately conservative and leans on
# classify_one() to do the real filtering, not this number alone).
CALL_COUNT_THRESHOLD = 15

# Canonical, deterministically-deployed infra contracts that appear at
# the same address across most EVM chains. These are shared plumbing,
# not "a project someone built" — classify them immediately without
# spending a GeckoTerminal call on them, and never surface them as if
# they were a discovered Arc-native project.
KNOWN_INFRA_CONTRACTS = {
    "0x000000000022d473030f116ddee9f6b43ac78ba3": "Uniswap Permit2",
    "0x0000000071727de22e5e9d8baf0edac6f37da032": "ERC-4337 EntryPoint v0.7",
}

GECKOTERMINAL_TOKEN_INFO_URL = (
    "https://pro-api.coingecko.com/api/v3/onchain/networks/arc/tokens/{address}/info"
)


def _client():
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def upsert_unmapped_contracts(db=None) -> int:
    """Pull distinct unmapped contract_addresses from gas_events and
    upsert call_count/first_seen/last_seen into discovered_contracts.
    Returns the number of distinct contracts touched this run."""
    db = db or _client()
    now = datetime.now(timezone.utc).isoformat()

    # One row per unmapped contract, with its count and time bounds.
    # Supabase's Python client doesn't do raw GROUP BY, so this pulls
    # the unmapped rows and aggregates in Python — fine at current
    # mainnet volume, revisit if gas_events grows large enough for this
    # to matter (same caveat ingestion/worker.py already tracks for
    # blocks-per-run, see docs/BUGS.md #5).
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


def _gecko_token_info(address: str) -> dict | None:
    """Query GeckoTerminal's onchain token-info endpoint. Returns None on
    404 (not indexed — no pool yet) or any request failure; never
    raises, since a classification miss should just leave the candidate
    unclassified, not break the ingestion run."""
    if not COINGECKO_API_KEY:
        return None
    try:
        resp = requests.get(
            GECKOTERMINAL_TOKEN_INFO_URL.format(address=address),
            headers={"x-cg-pro-api-key": COINGECKO_API_KEY},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("data", {}).get("attributes")
    except requests.RequestException:
        return None


def classify_one(address: str) -> dict:
    """Classify a single candidate contract. Returns a dict with
    category/gecko_symbol/gecko_name/gecko_score/gecko_is_honeypot,
    category=None if no real signal was found."""
    address = address.lower()

    if address in KNOWN_INFRA_CONTRACTS:
        return {
            "category": "infra",
            "gecko_symbol": None,
            "gecko_name": KNOWN_INFRA_CONTRACTS[address],
            "gecko_score": None,
            "gecko_is_honeypot": None,
        }

    attrs = _gecko_token_info(address)
    if attrs:
        return {
            "category": "token",
            "gecko_symbol": attrs.get("symbol"),
            "gecko_name": attrs.get("name"),
            "gecko_score": attrs.get("gt_score"),
            "gecko_is_honeypot": str(attrs.get("is_honeypot")),
        }

    # No GeckoTerminal-indexed token (no pool yet) and not known infra.
    # TODO: event-topic heuristic here (does it look like a DEX pool
    # from its Transfer/Swap event shape in gas_events/token_flows?)
    # before giving up — not yet implemented, this is the next piece.
    return {
        "category": None,
        "gecko_symbol": None,
        "gecko_name": None,
        "gecko_score": None,
        "gecko_is_honeypot": None,
    }


def classify_candidates(db=None) -> int:
    """Classify every 'unclassified' candidate at or above
    CALL_COUNT_THRESHOLD. Returns the number classified this run."""
    db = db or _client()
    now = datetime.now(timezone.utc).isoformat()

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
        result = classify_one(addr)
        new_status = "needs_review" if result["category"] else "unclassified"
        db.table("discovered_contracts").update(
            {
                **result,
                "status": new_status,
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
    promoted this run."""
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
    for row in ready:
        addr = row["contract_address"]
        # slug: prefer the gecko symbol/name if we have one, else the
        # address itself — never block promotion on naming.
        slug_source = (row.get("gecko_symbol") or row.get("gecko_name") or addr).lower()
        project_id = "".join(c if c.isalnum() else "-" for c in slug_source).strip("-")

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

    return promoted


def run_discovery() -> dict:
    """Full discovery pass: upsert -> classify -> promote. Call once per
    ingestion cycle, after the normal block-processing pass."""
    db = _client()
    touched = upsert_unmapped_contracts(db)
    classified = classify_candidates(db)
    promoted = promote_ready_candidates(db)
    return {"touched": touched, "classified": classified, "promoted": promoted}


if __name__ == "__main__":
    result = run_discovery()
    print(f"Discovery run: {result['touched']} contracts touched, "
          f"{result['classified']} classified, {result['promoted']} promoted.")
