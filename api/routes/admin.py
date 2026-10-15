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

Categories are validated against the pipeline's own taxonomy
(aggregate.SEGMENT_BY_CATEGORY). A free-text category such as "DeFi protocol" would be stored
as-is and the project would silently land in the "other" segment (no TVL, no score), so an
unknown category is a 422, not a guess. The list the admin UI offers comes from GET /admin/categories.
"""

import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from admin_auth import verify_admin_key
from aggregate import SEGMENT_BY_CATEGORY
from db import get_write_client
from models import AdminClassifyRequest, AdminReviewRequest, AdminSubmission

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_admin_key)])

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_MAX_NOTE = 500
_DISCOVERED_STATUSES = ("unclassified", "needs_review", "promoted", "rejected")


def _clean_category(value: str | None) -> str:
    """Lowercase + validate against the taxonomy. Raises 422 with the allowed list."""
    cat = (value or "").strip().lower()
    if cat not in SEGMENT_BY_CATEGORY:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown category {value!r}. Use one of: {', '.join(sorted(SEGMENT_BY_CATEGORY))}.",
        )
    return cat


def _clean_address(value: str) -> str:
    if not _ADDRESS_RE.match((value or "").strip()):
        raise HTTPException(status_code=422, detail="contract_address must be 0x followed by 40 hex characters")
    return value.strip().lower()


def _clean_text(value: str | None, field: str) -> str | None:
    value = (value or "").strip()
    if len(value) > _MAX_NOTE:
        raise HTTPException(status_code=422, detail=f"{field} must be under {_MAX_NOTE} characters")
    return value or None


@router.get("/categories", response_model=list[dict])
def list_categories():
    """The accepted categories and the segment each one maps to (what decides which metrics the
    project gets). The admin UI builds its dropdown from this so it can never drift from the API."""
    return [
        {"category": cat, "segment": seg}
        for cat, seg in sorted(SEGMENT_BY_CATEGORY.items(), key=lambda kv: (kv[1], kv[0]))
    ]


@router.get("/submissions", response_model=list[AdminSubmission])
def list_submissions(
    status: Literal["pending", "approved", "rejected", "all"] = "pending",
    limit: int = Query(100, ge=1, le=200),
    client=Depends(get_write_client),
):
    """Project-owner submissions. Pending (the default) is oldest first, so the longest wait is
    reviewed first; the history views are newest first."""
    query = client.table("project_submissions").select("*")
    if status != "all":
        query = query.eq("status", status)
    result = query.order("created_at", desc=(status != "pending")).limit(limit).execute()
    return result.data or []


@router.get("/discovered", response_model=list[dict])
def list_discovered(
    status: Literal["unclassified", "needs_review", "promoted", "rejected"] = "unclassified",
    limit: int = Query(50, ge=1, le=200),
    client=Depends(get_write_client),
):
    """Browse discovered_contracts by status — lets a reviewer see
    high-call-count 'unclassified' candidates GeckoTerminal couldn't
    identify, as targets for a manual /admin/classify call. 'needs_review'
    shows what has been classified and is waiting for the next promotion run."""
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
    """
    Set a contract's category/name and queue it for promotion.

    Existing rows get a plain UPDATE; only unseen addresses are INSERTed.
    (Fixed 2026-10-06: this used to upsert in both cases. PostgREST's upsert is
    INSERT ... ON CONFLICT DO UPDATE, and Postgres checks NOT NULL on the
    proposed row BEFORE it notices the conflict - so for any address already in
    discovered_contracts the missing first_seen/last_seen raised a not-null
    violation and the route returned a 500. It only ever worked for brand-new
    addresses, which is not the case that matters: manual review is for
    contracts discovery has already seen.)
    """
    now = datetime.now(timezone.utc).isoformat()
    address = address.lower()

    existing = (
        client.table("discovered_contracts")
        .select("contract_address")
        .eq("contract_address", address)
        .execute()
    )
    fields = {
        "category": category,
        "gecko_name": name,
        "status": "needs_review",
        "classified_at": now,
        "updated_at": now,
    }
    if existing.data:
        client.table("discovered_contracts").update(fields).eq("contract_address", address).execute()
    else:
        client.table("discovered_contracts").insert(
            {"contract_address": address, "call_count": 0, "first_seen": now, "last_seen": now, **fields}
        ).execute()


@router.post("/classify")
def classify(body: AdminClassifyRequest, client=Depends(get_write_client)):
    """Manual override: set a contract's category directly. Promotes on
    the next scheduled discovery run, same as every other classified
    candidate — see module docstring."""
    address = _clean_address(body.contract_address)
    category = _clean_category(body.category)
    name = _clean_text(body.name, "name")
    _manual_classify(client, address, category, name)
    return {"status": "ok", "contract_address": address, "category": category,
            "segment": SEGMENT_BY_CATEGORY[category],
            "note": "Will be promoted on the next scheduled discovery run."}


@router.post("/discovered/{address}/reject")
def reject_discovered(address: str, client=Depends(get_write_client)):
    """Dismiss a discovered contract (junk, scam, not worth tracking). It leaves the unclassified
    list. A contract that has already been promoted to a project cannot be dismissed here."""
    address = _clean_address(address)
    found = (
        client.table("discovered_contracts")
        .select("contract_address, status")
        .eq("contract_address", address)
        .limit(1)
        .execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="No discovered contract with that address")
    if found.data[0]["status"] == "promoted":
        raise HTTPException(status_code=409, detail="Already a tracked project; it cannot be dismissed from here")
    now = datetime.now(timezone.utc).isoformat()
    client.table("discovered_contracts").update({"status": "rejected", "updated_at": now}).eq(
        "contract_address", address
    ).execute()
    return {"status": "ok", "contract_address": address}


@router.post("/submissions/{submission_id}/review")
def review(submission_id: int, body: AdminReviewRequest, client=Depends(get_write_client)):
    """Approve or reject a pending submission. Approving requires a valid category
    (the one supplied here, or the submitter's proposed one if it is in the taxonomy):
    a submission can't be approved into limbo with no classification.

    Everything is validated BEFORE anything is written. Previously the submission was marked
    'approved' first and the missing-category error came after, which took it out of the pending
    queue with nothing queued for promotion. Approving now queues the contract first and marks the
    submission second, so a failure in between leaves it pending to retry."""
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

    reviewer_note = _clean_text(body.note, "note")

    if body.decision == "approve":
        category_in = body.category or submission.get("proposed_category")
        if not (category_in or "").strip():
            raise HTTPException(
                status_code=422,
                detail="Pick a category: the submitter didn't propose one and none was given.",
            )
        category = _clean_category(category_in)
        name = _clean_text(body.name, "name") or _clean_text(submission.get("proposed_name"), "name")
        _manual_classify(client, submission["contract_address"], category, name)

    client.table("project_submissions").update(
        {
            "status": "approved" if body.decision == "approve" else "rejected",
            "reviewed_at": now,
            "reviewer_note": reviewer_note,
        }
    ).eq("id", submission_id).execute()

    return {"status": "ok", "submission_id": submission_id, "decision": body.decision}
