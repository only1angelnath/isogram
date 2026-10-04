"""
check_needs_review.py — batch-query explorer.arc.io's Blockscout API for
every 'needs_review' candidate, instead of opening 23 browser tabs.

Blockscout (which powers explorer.arc.io) exposes a JSON API at
/api/v2/addresses/{address} with verification status, contract name (if
verified), and token metadata (if it's an ERC-20). This pulls that for
every candidate currently stuck in needs_review/category=null and prints
a compact summary — enough to triage most of them without ever opening
the explorer UI, and to know exactly which handful genuinely need a closer
manual look.

Usage: python check_needs_review.py
"""

import requests
from dotenv import load_dotenv

load_dotenv()

from db import get_client

EXPLORER_API_BASE = "https://explorer.arc.io/api/v2/addresses/{address}"
# explorer.arc.io is Cloudflare-fronted and silently blocks requests' default
# User-Agent ("python-requests/x.x") — confirmed live 2026-10-01: identical
# requests succeeded with a browser-like UA and failed (no response at all)
# without one, across all 23 test addresses uniformly.
_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def fetch_address_info(address: str) -> dict | None:
    try:
        resp = requests.get(EXPLORER_API_BASE.format(address=address), headers=_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        return resp.json()
    except requests.RequestException:
        return None


def summarize(address: str, info: dict | None, call_count: int) -> str:
    if info is None:
        return f"{address} (calls={call_count}): [no response from explorer API]"

    is_contract = info.get("is_contract", False)
    if not is_contract:
        return f"{address} (calls={call_count}): NOT A CONTRACT (unexpected — EOA filter should have caught this)"

    name = info.get("name")
    is_verified = info.get("is_verified", False)
    is_scam = info.get("is_scam", False)
    token = info.get("token")  # non-null if Blockscout recognizes it as a token contract
    proxy_type = info.get("proxy_type")
    implementations = info.get("implementations") or []

    parts = [f"{address} (calls={call_count}):"]
    if is_scam:
        parts.append("[FLAGGED AS SCAM BY EXPLORER]")
    if is_verified and name:
        parts.append(f"VERIFIED as \"{name}\"")
    else:
        parts.append("unverified")

    if token:
        parts.append(f"| TOKEN symbol={token.get('symbol')} name={token.get('name')} type={token.get('type')}")

    if proxy_type:
        impl_names = ", ".join(i.get("name", "?") for i in implementations) or "unknown impl"
        parts.append(f"| PROXY ({proxy_type}) -> {impl_names}")

    return " ".join(parts)


def main():
    client = get_client()
    resp = (
        client.table("discovered_contracts")
        .select("contract_address, call_count")
        .eq("status", "needs_review")
        .is_("category", "null")
        .order("call_count", desc=True)
        .execute()
    )
    rows = resp.data or []
    print(f"Checking {len(rows)} candidates against explorer.arc.io...\n")

    for row in rows:
        addr = row["contract_address"]
        info = fetch_address_info(addr)
        print(summarize(addr, info, row["call_count"]))


if __name__ == "__main__":
    main()
