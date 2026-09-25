"""
ingestion/admin_tools.py

Manual classification override and project-submission review — the two
non-automated paths onto the "worth tracking" list, alongside
discovery.py's automated GeckoTerminal/known-infra classification.

Both paths land a candidate at discovered_contracts.status='needs_review'
with a real category, then promote_ready_candidates() (discovery.py)
promotes it into `projects` on the next scheduled run — same hybrid gate,
same code path, whether the classification came from GeckoTerminal, an
admin's judgment call, or a project owner's own submission. Nothing here
inserts into `projects` directly.

Usage (run manually, needs SUPABASE_URL / SUPABASE_SERVICE_KEY set):

    python admin_tools.py list-pending
    python admin_tools.py review <submission_id> approve --category token --name "My Project"
    python admin_tools.py review <submission_id> reject --note "not on Arc mainnet"
    python admin_tools.py classify 0xabc... --category dex --name "Some DEX"
"""

import argparse
import sys
from datetime import datetime, timezone

from discovery import _client


def manual_classify(address: str, category: str, name: str | None = None, db=None) -> None:
    """
    Admin override: set a candidate's category directly, regardless of
    call_count or what (if anything) automated classification found.
    Upserts, so this works even for an address discovery hasn't seen yet
    (e.g. an admin knows about a project before it has enough on-chain
    volume to reach CALL_COUNT_THRESHOLD on its own).
    """
    db = db or _client()
    now = datetime.now(timezone.utc).isoformat()
    address = address.lower()

    existing = (
        db.table("discovered_contracts")
        .select("contract_address")
        .eq("contract_address", address)
        .execute()
    )
    row = {
        "contract_address": address,
        "category": category,
        "gecko_name": name,
        "status": "needs_review",
        "classified_at": now,
        "updated_at": now,
    }
    if not existing.data:
        # brand-new address discovery hasn't logged yet
        row.update({"call_count": 0, "first_seen": now, "last_seen": now})
    db.table("discovered_contracts").upsert(row, on_conflict="contract_address").execute()
    print(f"Set {address} -> category={category!r}, status=needs_review "
          f"(will promote on next discovery run).")


def list_pending_submissions(db=None) -> list[dict]:
    db = db or _client()
    result = (
        db.table("project_submissions")
        .select("*")
        .eq("status", "pending")
        .order("created_at")
        .execute()
    )
    return result.data or []


def review_submission(
    submission_id: int,
    decision: str,
    category: str | None = None,
    name: str | None = None,
    note: str | None = None,
    db=None,
) -> None:
    """
    decision: 'approve' or 'reject'. On approve, feeds the submission's
    contract into manual_classify() (using the reviewer's chosen
    category/name if given, falling back to what the submitter proposed).
    """
    db = db or _client()
    now = datetime.now(timezone.utc).isoformat()

    result = (
        db.table("project_submissions")
        .select("*")
        .eq("id", submission_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        print(f"No submission with id={submission_id}", file=sys.stderr)
        sys.exit(1)
    submission = result.data[0]

    db.table("project_submissions").update(
        {"status": "approved" if decision == "approve" else "rejected",
         "reviewed_at": now, "reviewer_note": note}
    ).eq("id", submission_id).execute()

    if decision == "approve":
        final_category = category or submission.get("proposed_category")
        final_name = name or submission.get("proposed_name")
        if not final_category:
            print(
                f"Submission {submission_id} approved but has no category "
                f"(submitter didn't propose one and none given via --category) "
                f"— run `classify` separately or pass --category now.",
                file=sys.stderr,
            )
            return
        manual_classify(submission["contract_address"], final_category, final_name, db=db)
    else:
        print(f"Submission {submission_id} rejected.")


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-pending")

    classify_p = sub.add_parser("classify")
    classify_p.add_argument("address")
    classify_p.add_argument("--category", required=True)
    classify_p.add_argument("--name")

    review_p = sub.add_parser("review")
    review_p.add_argument("submission_id", type=int)
    review_p.add_argument("decision", choices=["approve", "reject"])
    review_p.add_argument("--category")
    review_p.add_argument("--name")
    review_p.add_argument("--note")

    args = parser.parse_args()

    if args.command == "list-pending":
        for row in list_pending_submissions():
            print(f"[{row['id']}] {row['contract_address']} "
                  f"name={row.get('proposed_name')!r} "
                  f"category={row.get('proposed_category')!r} "
                  f"submitted={row['created_at']}")
    elif args.command == "classify":
        manual_classify(args.address, args.category, args.name)
    elif args.command == "review":
        review_submission(
            args.submission_id, args.decision,
            category=args.category, name=args.name, note=args.note,
        )


if __name__ == "__main__":
    _main()
