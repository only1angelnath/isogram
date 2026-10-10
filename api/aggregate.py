"""
aggregate.py — pure data-shaping logic for the API layer.

Kept separate from db.py (network calls) and routes/ (FastAPI wiring) so it's
unit-testable with fabricated rows, same pattern as scoring/compute_scores.py
and ingestion/worker.py's process_block().

project_scores has one row per project per computation run (see
docs/SCHEMA.md) — everything here works from "the latest row per project,"
never an average or a sum across runs.
"""

import html
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

# Category -> segment. MUST match scoring/segments.py (tests/test_segments_sync.py in scoring/
# fails on drift). A segment decides which metrics make sense for a project
# (DeFiLlama-style): TVL means something for a DEX or lender, nothing for a router
# proxy or a memecoin; the composite score only makes sense inside a peer group of
# comparable DeFi protocols. Unknown / missing category -> "other" (never guessed).
SEGMENT_BY_CATEGORY = {
    "dex": "defi", "lending": "defi", "yield": "defi", "liquid-staking": "defi",
    "launchpad": "launchpad",
    "infra": "infra", "bridge": "infra", "oracle": "infra", "governance": "infra",
    "stablecoin": "stablecoin", "institutional": "stablecoin",
    "token": "token", "meme": "token", "wrapped": "token",
}


def segment_for(category: Optional[str]) -> str:
    return SEGMENT_BY_CATEGORY.get((category or "").strip().lower(), "other")


# A pipeline whose last applied block is older than this is reported as "behind".
LIVE_LAG_SECONDS = 600

# Token symbols for the 6-decimal tokens the rollups track.
TOKEN_SYMBOLS = {
    "0x3600000000000000000000000000000000000000": "USDC",
    "0xbef5f6d51cb62b58e6a8f77868681825c6fe21c1": "EURC",
    "0x8a5d989bbb96929f689b0200f435f53da42bf490": "USYC",
}


# --- Third-party market data (docs/decisions/ADR-005) -----------------------------------
# Only these segments are priced: no TVL and no score under ADR-004, so their own token is the market
# signal (for a launchpad that is the platform token, which is the row's first contract).
MARKET_SEGMENTS = {"token", "stablecoin", "launchpad"}
MARKET_STALE_AFTER = timedelta(hours=24)   # refreshed hourly; older than this = unavailable
THIN_LIQUIDITY_USD = 10_000                # below this the price is easily moved or meaningless
INACTIVE_VOLUME_RATIO = 0.01               # 24h volume under 1% of liquidity = barely traded
HOLDERS_STALE_AFTER = timedelta(hours=72)   # refreshed ~every 12h; older than 3 days = unknown
VOLUME_7D_STALE_AFTER = timedelta(hours=48)  # 7d volume refreshes every ~6h; older than 2 days = unknown


def latest_score_by_project(score_rows: list[dict]) -> dict[str, dict]:
    """
    Given raw project_scores rows (possibly many computation runs per
    project), return {project_id: latest_row}. Rows are compared by
    computed_at (ISO string comparison works since all timestamps are UTC
    and the same format from Postgres).
    """
    latest: dict[str, dict] = {}
    for row in score_rows:
        project_id = row["project_id"]
        current = latest.get(project_id)
        if current is None or row["computed_at"] > current["computed_at"]:
            latest[project_id] = row
    return latest


def _to_float(value) -> Optional[float]:
    """Best-effort numeric coercion. None/unparsable input -> None, never a crash."""
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _rate(numerator, denominator) -> Optional[float]:
    """numerator/denominator as a float; None (not 0) when there is nothing to divide by."""
    try:
        n, d = Decimal(str(numerator)), Decimal(str(denominator))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if d <= 0:
        return None
    return float(n / d)


def build_market(row: Optional[dict], now: Optional[datetime] = None) -> Optional[dict]:
    """token_market_data row -> API `market` object, or None when there is nothing trustworthy
    to show (no row, no price, or a row older than MARKET_STALE_AFTER).

    Quality: thin (liquidity unknown or under $10k) > inactive (liquidity but ~no trading) > ok.
    FDV and market cap are withheld unless quality is ok: FDV is price x supply, so it inherits
    every flaw of the price (a $39M pool nobody trades once produced a $357B 'FDV').
    """
    if not row:
        return None
    fetched = _parse_iso(row.get("fetched_at"))
    if fetched is not None and fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if fetched is None or now - fetched > MARKET_STALE_AFTER:
        return None
    price = _to_float(row.get("price_usd"))
    if price is None or price <= 0:
        return None
    liquidity = _to_float(row.get("liquidity_usd"))
    volume = _to_float(row.get("volume_24h_usd"))
    if liquidity is None or liquidity < THIN_LIQUIDITY_USD:
        quality = "thin"
    elif volume is None or volume < liquidity * INACTIVE_VOLUME_RATIO:
        quality = "inactive"
    else:
        quality = "ok"
    ok = quality == "ok"
    volume_7d = _to_float(row.get("volume_7d_usd"))
    vol7_fetched = _parse_iso(row.get("volume_7d_fetched_at"))
    if vol7_fetched is not None and vol7_fetched.tzinfo is None:
        vol7_fetched = vol7_fetched.replace(tzinfo=timezone.utc)
    if vol7_fetched is None or now - vol7_fetched > VOLUME_7D_STALE_AFTER:
        volume_7d = None
    return {
        "price_usd": price,
        "fdv_usd": _to_float(row.get("fdv_usd")) if ok else None,
        "market_cap_usd": _to_float(row.get("market_cap_usd")) if ok else None,
        "liquidity_usd": liquidity,
        "volume_24h_usd": volume,
        "volume_7d_usd": volume_7d,
        "quality": quality,
        "listed_on_coingecko": bool((row.get("coingecko_coin_id") or "").strip()),
        "source": row.get("source") or "geckoterminal",
        "fetched_at": row["fetched_at"],
    }


def build_holders(row: Optional[dict], now: Optional[datetime] = None) -> Optional[int]:
    """token_holders row -> holder count, or None when unknown: no row, a cached 404 (NULL count),
    an unreadable count, or a row older than HOLDERS_STALE_AFTER. Zero is a real value."""
    if not row:
        return None
    count = row.get("holders_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        try:
            count = int(str(count)) if count is not None and str(count).strip().isdigit() else None
        except ValueError:
            count = None
    if count is None:
        return None
    fetched = _parse_iso(row.get("fetched_at"))
    if fetched is None:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return count if (now or datetime.now(timezone.utc)) - fetched <= HOLDERS_STALE_AFTER else None


def market_by_address(market_rows: list[dict]) -> dict[str, dict]:
    return {(r.get("contract_address") or "").lower(): r for r in market_rows or []}


def build_project_summary(project: dict, score_row: Optional[dict], market_row: Optional[dict] = None,
                          now: Optional[datetime] = None, holders_row: Optional[dict] = None) -> dict:
    """
    Merge a `projects` row with its latest `project_scores` row (if any) into
    one API-facing dict. A project with no score yet (brand new, or the
    scoring job hasn't run since it was added) gets explicit nulls, never a
    fabricated zero that would look like a real "no activity" measurement
    (see docs/BUGS.md #3).

    `tier`: "curated" for hand-seeded projects (projects.seeded), "discovered"
    for everything auto-promoted by discovery - so clients can keep the
    ecosystem list separate from the long tail of launchpad tokens.
    """
    tx = score_row.get("tx_count_7d") if score_row else None
    failed = score_row.get("failed_tx_7d") if score_row else None
    users = score_row.get("unique_users_7d") if score_row else None
    if users == 0 and tx:
        # Every transaction has a sender, so "transactions but zero users" cannot be
        # real: the contract was not tracked for senders when those days were ingested
        # (it was promoted after). Report "not measured", never a false 0.
        users = None
    return {
        "id": project["id"],
        "name": project["name"],
        "category": project.get("category"),
        "segment": segment_for(project.get("category")),
        "tier": "curated" if project.get("seeded") else "discovered",
        "score": _to_float(score_row["score"]) if score_row else None,
        "tvl_usd": _to_float(score_row.get("tvl_usd")) if score_row else None,
        "usdc_gas_7d": _to_float(score_row.get("usdc_gas_7d")) if score_row else None,
        "unique_users_7d": users,
        "tx_count_7d": tx,
        "failed_tx_7d": failed,
        "failed_rate_7d": _rate(failed, tx) if (tx is not None and failed is not None) else None,
        "computed_at": score_row.get("computed_at") if score_row else None,
        "market": build_market(market_row, now) if segment_for(project.get("category")) in MARKET_SEGMENTS else None,
        "holders": build_holders(holders_row, now) if segment_for(project.get("category")) in MARKET_SEGMENTS else None,
    }


def primary_contract(project: dict) -> Optional[str]:
    contracts = project.get("contracts") or []
    return contracts[0].lower() if contracts else None


def build_all_summaries(projects: list[dict], score_rows: list[dict],
                        market_rows: Optional[list[dict]] = None, now: Optional[datetime] = None,
                        holders_rows: Optional[list[dict]] = None) -> list[dict]:
    """Build a project summary for every tracked project, scored or not."""
    latest = latest_score_by_project(score_rows)
    markets = market_by_address(market_rows or [])
    holders = market_by_address(holders_rows or [])      # same {lowercased contract: row} shape
    return [
        build_project_summary(p, latest.get(p["id"]), markets.get(primary_contract(p) or ""), now,
                              holders.get(primary_contract(p) or ""))
        for p in projects
    ]


def top_by_metric(summaries: list[dict], metric: str, limit: int) -> list[dict]:
    """
    Rank summaries by `metric` descending, treating a null value (no score
    yet) as excluded rather than as zero — an unscored project competing at
    the bottom of a leaderboard by fiat would misrepresent "no data" as "no
    activity."
    """
    scored = [s for s in summaries if s.get(metric) is not None]
    scored.sort(key=lambda s: s[metric], reverse=True)
    return scored[:limit]


def build_network_summary(projects: list[dict], score_rows: list[dict], network_stats_row: Optional[dict]) -> dict:
    """
    Network-wide stat-strip data (docs/BRANDING.md §5). total_projects and
    total_scored come from the same project/score data every other route
    already reads; total_tvl_usd is a simple sum across current latest
    scores (no new pipeline data needed — TVL is already per-project).
    total_volume_7d / total_tx_7d / total_unique_users_7d come from
    network_stats (see db.fetch_network_stats), which IS new pipeline
    output — None on every one of those fields if the scoring job hasn't
    run yet, never a fabricated 0 (docs/BUGS.md #3).
    """
    summaries = build_all_summaries(projects, score_rows)
    total_scored = sum(1 for s in summaries if s["score"] is not None)
    tvl_values = [s["tvl_usd"] for s in summaries if s["tvl_usd"] is not None]
    total_tvl_usd = sum(tvl_values) if tvl_values else None

    score_values = [s["score"] for s in summaries if s["score"] is not None]
    avg_score = (sum(score_values) / len(score_values)) if score_values else None

    return {
        "total_projects": len(projects),
        "total_scored": total_scored,
        "total_tvl_usd": total_tvl_usd,
        "avg_score": avg_score,
        "total_volume_7d": _to_float(network_stats_row["total_volume_7d"]) if network_stats_row else None,
        "total_tx_7d": network_stats_row.get("total_tx_7d") if network_stats_row else None,
        "total_unique_users_7d": network_stats_row.get("total_unique_users_7d") if network_stats_row else None,
        "computed_at": network_stats_row.get("computed_at") if network_stats_row else None,
    }


def render_badge_svg(project_name: str, score: Optional[float], unscored_label: Optional[str] = None) -> str:
    """
    Render a minimal shields.io-style SVG badge. Falls back to an honest label rather than a
    fabricated 0.0-looking score when a project has no score: "insufficient data" for a DeFi
    project not yet scored, or `unscored_label` (e.g. "not scored") for a project type that
    is never scored (ADR-004).

    The name comes from PUBLIC on-chain token metadata that anyone can set, so every string
    is XML-escaped: an unescaped "&" breaks the image, and an unescaped "<script>" in an SVG
    opened directly from the API's own domain would execute.
    """
    label = project_name
    value = f"{score:.2f}" if score is not None else (unscored_label or "insufficient data")
    color = "#5FC9C0" if score is not None else "#8f8d86"  # Isogram verdigris / ink-dim
    esc_label = html.escape(label, quote=True)
    esc_value = html.escape(value, quote=True)

    label_width = 10 + 7 * len(label)
    value_width = 10 + 7 * len(value)
    total_width = label_width + value_width

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{esc_label}: {esc_value}">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#101012"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#f2f0ea" text-anchor="middle" font-family="Verdana,Geneva,sans-serif" font-size="11">
    <text x="{label_width / 2}" y="14">{esc_label}</text>
    <text x="{label_width + value_width / 2}" y="14">{esc_value}</text>
  </g>
</svg>"""


# --- Rollup-backed series (2026-10-04) ----------------------------------------

def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def build_pipeline_status(row: Optional[dict], now: Optional[datetime] = None) -> dict:
    """
    Freshness of the data, measured: data_through is the timestamp of the last
    block ingestion has applied. status: "live" when it is within LIVE_LAG_SECONDS
    of now, "behind" when ingestion is catching up or stalled, "unknown" before the
    first timestamped batch. Clients should read this before trusting "latest" values.
    """
    now = now or datetime.now(timezone.utc)
    through = _parse_iso(row.get("data_through")) if row else None
    lag = max(0, int((now - through).total_seconds())) if through else None
    if through is None:
        status = "unknown"
    else:
        status = "live" if lag <= LIVE_LAG_SECONDS else "behind"
    return {
        "status": status,
        "last_block_number": row.get("last_block_number") if row else None,
        "data_through": through.isoformat() if through else None,
        "lag_seconds": lag,
        "checkpoint_updated_at": row.get("checkpoint_updated_at") if row else None,
    }


def build_network_daily(rows: list[dict], today: Optional[str] = None,
                        data_through: Optional[str] = None) -> list[dict]:
    """
    Shape daily_network_metrics rows for the API with derived rates.

    `partial` is True for any day that is not fully covered: the day containing
    `data_through` (the last block ingestion has applied) and every later day. It
    falls back to "today (UTC) or later" only when freshness is unknown. This
    matters while ingestion is catching up: a day can be in the past yet still
    incomplete. `source` is passed through: "raw_backfill" days predate rollup
    ingestion, so their failed_tx_count / contract_creations / blocks are unknown
    and reported as None (never a misleading 0) - see docs/decisions/ADR-003.
    Derived: failed_rate (failed/tx), avg_gas_per_tx_usdc (gas/tx, 6-decimal view).
    """
    through = _parse_iso(data_through)
    boundary = through.date().isoformat() if through else (today or datetime.now(timezone.utc).date().isoformat())
    out = []
    for r in rows:
        backfill = r.get("source") == "raw_backfill"
        tx = r.get("tx_count")
        out.append({
            "day": r["day"],
            "tx_count": tx,
            "failed_tx_count": None if backfill else r.get("failed_tx_count"),
            "failed_rate": None if backfill else _rate(r.get("failed_tx_count"), tx),
            "usdc_gas_paid": _to_float(r.get("usdc_gas_paid")),
            "avg_gas_per_tx_usdc": _rate(r.get("usdc_gas_paid"), tx),
            "contract_creations": None if backfill else r.get("contract_creations"),
            "blocks": None if backfill else r.get("blocks"),
            "token_transfer_count": r.get("token_transfer_count"),
            "active_addresses": r.get("active_addresses"),
            "source": r.get("source"),
            "partial": (not backfill) and r["day"] >= boundary,
        })
    return out


def build_token_daily(rows: list[dict]) -> list[dict]:
    """Shape daily_token_metrics rows. volume is in the token's own 6-decimal
    units (never mixed across tokens); avg_transfer_size = volume / transfers."""
    out = []
    for r in rows:
        addr = (r.get("token_address") or "").lower()
        out.append({
            "day": r["day"],
            "token_address": addr,
            "symbol": TOKEN_SYMBOLS.get(addr),
            "transfer_count": r.get("transfer_count"),
            "volume": _to_float(r.get("volume")),
            "avg_transfer_size": _rate(r.get("volume"), r.get("transfer_count")),
        })
    return out


def build_top_contracts(rows: list[dict]) -> list[dict]:
    return [{
        "contract_address": r["contract_address"],
        "project_id": r.get("project_id"),
        "project_name": r.get("project_name"),
        "category": r.get("category"),
        "tx_count": r.get("tx_count"),
        "failed_tx_count": r.get("failed_tx_count"),
        "failed_rate": _rate(r.get("failed_tx_count"), r.get("tx_count")),
        "usdc_gas": _to_float(r.get("usdc_gas")),
        "gas_share": _to_float(r.get("gas_share")),
    } for r in rows]


def build_project_daily(rows: list[dict]) -> list[dict]:
    return [{
        "day": r["day"],
        "tx_count": r.get("tx_count"),
        "failed_tx_count": r.get("failed_tx_count"),
        "failed_rate": _rate(r.get("failed_tx_count"), r.get("tx_count")),
        "usdc_gas": _to_float(r.get("usdc_gas")),
        "unique_users": r.get("unique_users"),
    } for r in rows]


def build_score_history(rows: list[dict]) -> list[dict]:
    return [{
        "computed_at": r["computed_at"],
        "score": _to_float(r.get("score")),
        "tvl_usd": _to_float(r.get("tvl_usd")),
        "usdc_gas_7d": _to_float(r.get("usdc_gas_7d")),
        "unique_users_7d": r.get("unique_users_7d"),
    } for r in rows]

