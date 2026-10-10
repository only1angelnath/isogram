"""
Seed the Launchpads segment with real launchpad PLATFORMS (preview by default).

Sources of the contract lists, all re-checked on-chain by this script before it writes:
  - Argus: portal registry and token published at argus.world (bundle sha256 90059a60...abef,
    generated 2026-10-01); the ARGUS token comes from matching CoinGecko coin 'argus-2'.
  - BullCheese: the MintPlus / deployer / locker contracts from its Arc deployment notes. The
    shared Uniswap contracts it touches (V3 factory, position manager, router, Multicall3From)
    are deliberately NOT included: every launch on the chain uses them.
  - 11 CoinGecko launchpad tokens, matched by CoinGecko coin id in token_market_data and
    confirmed by on-chain name (2026-10-09). A copycat 'UBI.fun on Arc' shares the UBI symbol;
    only the CoinGecko-matched contract is used.

What it does (idempotent; hand-seeded rows are never touched):
  1. Marks each launchpad token's existing project category='launchpad', then seeded=true.
  2. Argus: one project holding the token plus Portals #1-#8; the two stub projects Isogram had
     created for Portal #7/#8 (filed under 'bridge') are merged into it and retired.
  3. BullCheese: a new project holding its six platform contracts.
Seeded projects are protected by the protect_seeded_project_fields trigger, so category and
contracts are written first and seeded=true is a separate, second update.

Run from the repo root:
    PYTHONPATH=ingestion python3 ops/seed_launchpads.py            # preview (also validates on-chain)
    PYTHONPATH=ingestion python3 ops/seed_launchpads.py --apply    # write
Optional: ARC_RPC_URL overrides the RPC (default https://rpc.mainnet.arc.io).
"""

import json
import os
import re
import sys
import urllib.request

CHAIN_ID = "0x13b2"
ARGUS_TOKEN = "0xece5ca8bf9220718e5727754026757512212cb3c"
ARGUS_PORTALS = {
    "#8 (launch portal)": "0xeed7559B8A6ABf64427dc41Cb5cc6400109C5D93",
    "#7": "0xB021Be536808f551b31789422Fd28a6c9c6e97Da",
    "#6": "0xA5628A11c412596E1f63b75a2C0284F843C549d6",
    "#5": "0x07a688a001f416cC433c68Ff56Aa26bC5131Cc6E",
    "#4": "0xa36c443A797771Df82533B8B4A86F0AFfd970862",
    "#3": "0x7A17Ab0106C46C0be30623F3EB7F299CC0058338",
    "#2": "0xBed9880A0ba12722ba4b8791c0B6F8c74338246C",
    "#1": "0x0F1C7Cb26D6cD36BD4189E41947658b39437587A",
}
BULLCHEESE = {
    "MintPlus": "0x16D4c13aD2A23288AA9b9384F24084edC8CBeF41",
    "Token deployer": "0x8Be8dF30809CFc8FB69B41a0FBD4A1391D973f4a",
    "Token implementation": "0x5FB8526D5FC7040959CB1a4f5a4dc88BF0468c28",
    "Locker deployer": "0x7c466B81335eD91a434711d661de17cb0E0B9AbB",
    "Locker implementation": "0x3C97Ba03df0F6152d2aAcD96d63591819e8440B8",
    "Team Finance locker": "0x154479cA34D77A176E74C038b70df102D9Be9935",
}
TOKENS = {  # CoinGecko coin id -> contract
    "faze": "0x394d38f807ee0027a182216f5e67a15ae441fa2e",
    "arcstocks": "0x4c9b47dbd5933aa4574b2c27f82419e4dbbd0222",
    "arctools": "0x1ea1e4f9a9975f1f6e9c0a9f6e8ada7a66e6de52",
    "ubi": "0xfa3ffdf775cc3f6ac82cd258fb948a8a21e1749e",
    "akarii": "0x643098f125e765081fec0b67384bfe5ca498f24a",
    "ellipse": "0x86f7424c3e1ebb3f42e1e687468e36d5f2a1222e",
    "memespad": "0x0bb3befba323578dad33efb6356c69b557787777",
    "arckit": "0xbc3764348131fe1962f267f442a8fe30459ededd",
    "tolly": "0xbc43ce8dec648ea298c4275559b81d6261c90b67",
    "long": "0x2164bb17a2d38c1b5170e987b2c0416df1efc752",
    "arcstockpad": "0x3dd6db0f20d747e1274839cdd6724cc5df1fb813",
}
NOT_YET_MAPPED = ("parabolic", "wonk")   # PARA / WONK: no contract found yet - reported, never guessed
WEBSITES = {"argus": "https://argus.world/", "bullcheese": "https://bullcheese.fun/"}

_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


def all_addresses() -> list:
    return [ARGUS_TOKEN, *ARGUS_PORTALS.values(), *BULLCHEESE.values(), *TOKENS.values()]


# ------------------------------------------------------------------ on-chain validation

def rpc_call(method: str, params: list, url: str | None = None):
    req = urllib.request.Request(
        url or os.environ.get("ARC_RPC_URL", "https://rpc.mainnet.arc.io"),
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "isogram-ops"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read()).get("result")
        except Exception:
            if attempt == 2:
                return None
    return None


def validate_on_chain(addresses: list, call=rpc_call) -> dict:
    """{address: code size in bytes}. Raises if the chain is wrong or any address is malformed."""
    if call("eth_chainId", []) != CHAIN_ID:
        raise RuntimeError(f"RPC is not Arc mainnet (wanted chain id {CHAIN_ID})")
    sizes = {}
    for a in addresses:
        if not _ADDR.match(a):
            raise RuntimeError(f"malformed address: {a!r}")
        code = call("eth_getCode", [a, "latest"]) or "0x"
        sizes[a.lower()] = (len(code) - 2) // 2
    return sizes


# ------------------------------------------------------------------ planning (pure)

def build_plan(projects: list) -> dict:
    index = {}
    for p in projects:
        for a in p.get("contracts") or []:
            index[a.lower()] = p
    plan = {"tokens": [], "done": [], "skipped": [], "missing": [], "retire": [], "conflicts": [],
            "argus": None, "bullcheese": None, "unmapped": []}

    for slug, addr in TOKENS.items():
        p = index.get(addr)
        if p is None:
            plan["missing"].append((slug, addr))
        elif p["category"] == "launchpad" and p["seeded"]:
            plan["done"].append(p["name"])
        elif p["seeded"]:
            plan["skipped"].append((p["name"], "hand-seeded under another category; change via migration"))
        else:
            plan["tokens"].append(p)

    argus = index.get(ARGUS_TOKEN)
    desired = [ARGUS_TOKEN]
    for label, portal in ARGUS_PORTALS.items():
        other = index.get(portal.lower())
        if other is not None and (argus is None or other["id"] != argus["id"]):
            if not other["seeded"] and all(c.lower() in {a.lower() for a in ARGUS_PORTALS.values()} for c in other["contracts"]):
                if other["id"] not in {r["id"] for r in plan["retire"]}:
                    plan["retire"].append(other)
            else:
                plan["conflicts"].append((portal, other["name"]))
                continue
        desired.append(portal.lower())
    if argus is None:
        plan["skipped"].append(("Argus", f"the ARGUS token {ARGUS_TOKEN} is not a tracked project"))
    elif argus["seeded"] and argus["category"] == "launchpad" and {c.lower() for c in argus["contracts"]} >= set(desired):
        plan["done"].append("Argus")
    elif argus["seeded"]:
        plan["skipped"].append(("Argus", "already hand-seeded with a different contract set; change via migration"))
    else:
        plan["argus"] = {"project": argus, "contracts": desired}

    bc = [a.lower() for a in BULLCHEESE.values()]
    clash = [(a, index[a]["name"]) for a in bc if a in index and index[a]["id"] != "bullcheese"]
    plan["conflicts"].extend(clash)
    bc_ok = [a for a in bc if a not in {c[0] for c in clash}]
    existing = next((p for p in projects if p["id"] == "bullcheese"), None)
    if existing and existing["seeded"] and {c.lower() for c in existing["contracts"]} >= set(bc_ok):
        plan["done"].append("BullCheese")
    else:
        plan["bullcheese"] = {"existing": existing, "contracts": bc_ok}

    for p in projects:
        n = (p["name"] or "").lower()
        if any(k in n for k in NOT_YET_MAPPED) and p["category"] != "launchpad":
            plan["unmapped"].append((p["name"], (p["contracts"] or [None])[0]))
    return plan


def print_plan(plan: dict, sizes: dict) -> None:
    def code(a): return f"{sizes.get(a.lower(), 0):>6,}B"
    print(f"launchpad tokens to mark: {len(plan['tokens'])}")
    for p in plan["tokens"]:
        print(f"  {p['name'][:26]:26} {p['category'] or '-':9} -> launchpad   {p['contracts'][0]}  {code(p['contracts'][0])}")
    if plan["argus"]:
        a = plan["argus"]
        print(f"Argus: project '{a['project']['id']}' -> launchpad with {len(a['contracts'])} contracts (token + portals)")
        for label, portal in ARGUS_PORTALS.items():
            if portal.lower() in a["contracts"]:
                print(f"    portal {label:20} {portal}  {code(portal)}")
    for r in plan["retire"]:
        print(f"  merge + retire stub project '{r['name']}' ({r['id']}, was {r['category']}) into Argus")
    if plan["bullcheese"]:
        b = plan["bullcheese"]
        print(f"BullCheese: {'update' if b['existing'] else 'create'} project 'bullcheese' with {len(b['contracts'])} contracts")
        for label, a in BULLCHEESE.items():
            if a.lower() in b["contracts"]:
                print(f"    {label:22} {a}  {code(a)}")
    if plan["done"]:
        print("already done:", ", ".join(plan["done"]))
    for slug, addr in plan["missing"]:
        print(f"NOT TRACKED: {slug} ({addr}) has no project; run discovery first")
    for name, why in plan["skipped"]:
        print(f"SKIPPED: {name}: {why}")
    for addr, name in plan["conflicts"]:
        print(f"CONFLICT: {addr} already belongs to '{name}'; left out of the new project")
    for name, addr in plan["unmapped"]:
        print(f"PARA/WONK candidate (not applied, confirm by hand): {name} {addr}")


# ------------------------------------------------------------------ writing

def _upd(client, table, values, **eq):
    q = client.table(table).update(values)
    for k, v in eq.items():
        q = q.eq(k, v)
    q.execute()


def retire_project(client, old_id: str, into_id: str) -> None:
    """Point every reference at the surviving project, drop the stub's scores, delete the stub.
    (The FKs from discovered_contracts / gas_events / project_scores have no ON DELETE CASCADE.)"""
    _upd(client, "discovered_contracts", {"promoted_project_id": into_id}, promoted_project_id=old_id)
    try:
        _upd(client, "gas_events", {"project_id": into_id}, project_id=old_id)
    except Exception as exc:
        # Legacy table. If rows still reference the stub, the delete below fails on the foreign key and
        # the run stops loudly BEFORE the Argus project is updated, so nothing is left half-merged.
        print(f"  note: gas_events repoint failed ({type(exc).__name__}); the delete will fail if rows remain")
    client.table("project_scores").delete().eq("project_id", old_id).execute()
    client.table("projects").delete().eq("id", old_id).execute()


def execute(client, plan: dict) -> None:
    for p in plan["tokens"]:
        _upd(client, "projects", {"category": "launchpad"}, id=p["id"])
        _upd(client, "projects", {"seeded": True}, id=p["id"])
        print(f"  marked {p['name']}")
    if plan["argus"]:
        a = plan["argus"]
        for r in plan["retire"]:
            retire_project(client, r["id"], a["project"]["id"])
            print(f"  retired stub {r['name']}")
        socials = dict(a["project"].get("socials") or {})
        socials.setdefault("website", WEBSITES["argus"])
        _upd(client, "projects", {"category": "launchpad", "contracts": a["contracts"], "socials": socials}, id=a["project"]["id"])
        _upd(client, "projects", {"seeded": True}, id=a["project"]["id"])
        print("  Argus updated")
    if plan["bullcheese"]:
        b = plan["bullcheese"]
        if b["existing"]:
            _upd(client, "projects", {"category": "launchpad", "contracts": b["contracts"]}, id="bullcheese")
            _upd(client, "projects", {"seeded": True}, id="bullcheese")
        else:
            client.table("projects").insert({
                "id": "bullcheese", "name": "BullCheese", "category": "launchpad", "contracts": b["contracts"],
                "socials": {"website": WEBSITES["bullcheese"]}, "seeded": True,
            }).execute()
        print("  BullCheese written")


def fetch_projects(client) -> list:
    rows, last = [], None
    while True:
        q = client.table("projects").select("id, name, category, contracts, seeded, socials")
        if last is not None:
            q = q.gt("id", last)
        page = q.order("id").limit(1000).execute().data or []
        rows.extend(page)
        if len(page) < 1000:
            return rows
        last = page[-1]["id"]


def run(client, apply: bool, call=rpc_call) -> dict:
    sizes = validate_on_chain(all_addresses(), call)
    empty = [a for a, n in sizes.items() if n == 0]
    if empty:
        print("NO CODE on Arc for:", *empty, sep="\n  ")
        raise SystemExit("refusing to continue: every address must have contract code on Arc (re-run if the RPC was flaky)")
    print(f"on-chain check: {len(sizes)} addresses, all have contract code on chain {CHAIN_ID}\n")
    plan = build_plan(fetch_projects(client))
    print_plan(plan, sizes)
    if not apply:
        print("\nPREVIEW ONLY - nothing written. Re-run with --apply to make the change.")
        return plan
    print()
    execute(client, plan)
    return plan


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    from db import get_client

    run(get_client(), apply="--apply" in sys.argv)
