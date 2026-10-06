"""
check_usdc_streams.py - measure how Arc's TWO USDC event streams relate on live
blocks (docs.arc.io/arc/references/usdc-system-events). Writes NOTHING.

Arc emits USDC Transfer logs from two emitters:
  * 0x3600...0000  ERC-20 interface, 6 decimals (what Isogram counts today)
  * 0xffff...fffe  native system log (EIP-7708), 18 decimals - logs EVERY
    explicit USDC movement exactly once (native sends, ERC-20 transfers, mint,
    burn). A plain native send emits ONLY this one.
An ERC-20 transfer() emits both, so the streams must never be added together.

This tells us how much real USDC movement the 6-decimal stream misses
(plain native sends) before we decide which stream defines "USDC volume".

Usage (from ingestion/, same env as the worker):
    python check_usdc_streams.py [N_BLOCKS]     # default 200
"""

import sys
import time
from decimal import Decimal

ERC20_USDC = "0x3600000000000000000000000000000000000000"
SYSTEM_EMITTER = "0xfffffffffffffffffffffffffffffffffffffffe"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_TOPIC = "0x" + "0" * 64


def _amount(log: dict, decimals: int) -> Decimal:
    data = log.get("data") or "0x"
    raw = int(data, 16) if data not in ("0x", "") else 0
    return Decimal(raw) / (Decimal(10) ** decimals)


def summarize_usdc_streams(blocks_receipts: list) -> dict:
    """blocks_receipts: list of receipt-lists (one per block). Pure function."""
    s = {"txs": 0, "erc20_logs": 0, "system_logs": 0, "native_only_txs": 0,
         "erc20_volume_usdc": Decimal(0), "system_volume_usdc": Decimal(0),
         "native_only_volume_usdc": Decimal(0), "system_mints": 0, "system_burns": 0}
    for receipts in blocks_receipts:
        for r in receipts:
            s["txs"] += 1
            has_erc20 = False
            sys_amount = Decimal(0)
            sys_seen = False
            for log in r.get("logs") or []:
                addr = (log.get("address") or "").lower()
                topics = log.get("topics") or []
                if len(topics) < 3 or topics[0].lower() != TRANSFER_TOPIC:
                    continue
                if addr == ERC20_USDC:
                    has_erc20 = True
                    s["erc20_logs"] += 1
                    s["erc20_volume_usdc"] += _amount(log, 6)
                elif addr == SYSTEM_EMITTER:
                    sys_seen = True
                    s["system_logs"] += 1
                    amt = _amount(log, 18)  # 18-dec native view -> human USDC, converted ONCE here
                    s["system_volume_usdc"] += amt
                    sys_amount += amt
                    if topics[1].lower() == ZERO_TOPIC:
                        s["system_mints"] += 1
                    if topics[2].lower() == ZERO_TOPIC:
                        s["system_burns"] += 1
            if sys_seen and not has_erc20:
                s["native_only_txs"] += 1
                s["native_only_volume_usdc"] += sys_amount
    return s


def main(n: int) -> None:
    from dotenv import load_dotenv

    load_dotenv()
    from rollup import process_batch  # noqa: F401  (ensures worker env/pool config is importable)
    from rollup import fetch_block
    from worker import _block_number_on_pool, _StickyPoolIndex, get_web3_pool
    from concurrent.futures import ThreadPoolExecutor

    pool, sticky = get_web3_pool(), _StickyPoolIndex()
    tip = _block_number_on_pool(pool, sticky)
    blocks = list(range(tip - n + 1, tip + 1))
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as ex:
        fetched = list(ex.map(lambda b: fetch_block(pool, sticky, b), blocks))
    s = summarize_usdc_streams([f[2] for f in fetched])
    print(f"{n} blocks ({blocks[0]}..{blocks[-1]}), {s['txs']} txs, {time.monotonic() - t0:.0f}s")
    for k, v in s.items():
        print(f"  {k}: {v}")
    if s["system_volume_usdc"]:
        miss = s["native_only_volume_usdc"] / s["system_volume_usdc"]
        print(f"  => the 6-decimal ERC-20 stream misses {miss:.1%} of system-logged USDC volume "
              f"(plain native sends), and {s['native_only_txs']} txs.")
    print("NOTHING WAS WRITTEN.")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
