"""
routes/admin.py — the admin-frontend backend.

Same logic as ingestion/admin_tools.py (list pending submissions,
approve/reject, manual classify -> discovered_contracts), reimplemented
here rather than imported, since api/ and ingestion/ are independently
deployed projects (see docs/SCAFFOLD.md). Both paths converge on the same
discovered_contracts.status='needs_review' + category state, so whichever
one runs, discovery.py's promote_ready_candidates() (run by the ingestion
cron) is what actually creates the projects row — nothing here inserts
into `projects` directly. That keeps "a human confirmed this" and "this
became a live tracked project" as two separate, auditable steps even
though they're now reachable from a UI instead of only the CLI.

Every route requires the X-Admin-Key header (see admin_auth.py).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from admin_auth import verify_admin_key
from db import get_write_client
from models import AdminClassifyRequest, AdminReviewRequest, SubmissionResponse

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_admin_key)])


@router.get("/submissions", response_model=list[SubmissionResponse])
def list_pending_submissions(client=Depends(get_write_client)):
    """Every project-owner submission still awaiting review."""
    result = (
        client.table("project_submissions")
        .select("*")
        .eq("status", "pending")
        .order("created_at")
        .execute()
    )
    return result.data or []


@router.get("/discovered", response_model=list[dict])
def list_discovered(status: str = "unclassified", limit: int = 50, client=Depends(get_write_client)):
    """Browse discovered_contracts by status — lets a reviewer see
    high-call-count 'unclassified' candidates GeckoTerminal couldn't
    identify, as targets for a manual /admin/classify call."""
    result = (
        client.table("discovered_contracts")
        .select("*")
        .eq("status", status)
        .order("call_count", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def _manual_classify(client, address: str, category: str, name: str | None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    address = address.lower()

    existing = (
        client.table("discovered_contracts")
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
        row.update({"call_count": 0, "first_seen": now, "last_seen": now})
    client.table("discovered_contracts").upsert(row, on_conflict="contract_address").execute()


@router.post("/classify")
def classify(body: AdminClassifyRequest, client=Depends(get_write_client)):
    """Manual override: set a contract's category directly. Promotes on
    the next scheduled discovery run, same as every other classified
    candidate — see module docstring."""
    _manual_classify(client, body.contract_address, body.category, body.name)
    return {"status": "ok", "contract_address": body.contract_address.lower(),
            "note": "Will be promoted on the next scheduled discovery run."}


@router.post("/submissions/{submission_id}/review")
def review(submission_id: int, body: AdminReviewRequest, client=Depends(get_write_client)):
    """Approve or reject a pending submission. Approving requires a
    category (the submitter's proposed one, or one supplied here) —
    a submission can't be approved into limbo with no classification."""
    now = datetime.now(timezone.utc).isoformat()

    result = (
        client.table("project_submissions")
        .select("*")
        .eq("id", submission_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail=f"No submission with id={submission_id}")
    submission = result.data[0]
    if submission["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Submission {submission_id} already {submission['status']}",
        )

    client.table("project_submissions").update(
        {
            "status": "approved" if body.decision == "approve" else "rejected",
            "reviewed_at": now,
            "reviewer_note": body.note,
        }
    ).eq("id", submission_id).execute()

    if body.decision == "approve":
        category = body.category or submission.get("proposed_category")
        name = body.name or submission.get("proposed_name")
        if not category:
            raise HTTPException(
                status_code=422,
                detail="No category available — submitter didn't propose one and none "
                       "was given. Reject, or resubmit the review with --category.",
            )
        _manual_classify(client, submission["contract_address"], category, name)

    return {"status": "ok", "submission_id": submission_id, "decision": body.decision}
