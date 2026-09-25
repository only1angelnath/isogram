"""
routes/submit.py — POST /submit

The one intentional write route in this API (see api/db.py's
get_write_client() docstring). A project owner proposes their contract for
listing; this never auto-promotes anything — it lands in
project_submissions with status='pending' for an admin to review via
ingestion/admin_tools.py. Classification (GeckoTerminal + admin judgment)
still happens normally; this is a signal, not a bypass.

Basic input hygiene here (lowercase + format check on the address, length
caps on free text) — real spam/abuse filtering is out of scope for the
Oct 14 deadline; the review queue is where junk gets caught for now.
"""

import re

from fastapi import APIRouter, Depends, HTTPException

from db import get_write_client, insert_submission
from models import SubmissionRequest, SubmissionResponse

router = APIRouter(tags=["submit"])

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_MAX_TEXT_LEN = 500


@router.post("/submit", response_model=SubmissionResponse, status_code=201)
def submit_project(body: SubmissionRequest, client=Depends(get_write_client)):
    """Submit a contract address for consideration as a tracked project."""
    if not _ADDRESS_RE.match(body.contract_address):
        raise HTTPException(
            status_code=422,
            detail="contract_address must be a valid 0x-prefixed 40-hex-character address",
        )
    for field_name, value in (
        ("proposed_name", body.proposed_name),
        ("proposed_category", body.proposed_category),
        ("submitter_contact", body.submitter_contact),
        ("note", body.note),
    ):
        if value and len(value) > _MAX_TEXT_LEN:
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} must be under {_MAX_TEXT_LEN} characters",
            )

    row = insert_submission(
        client,
        {
            "contract_address": body.contract_address.lower(),
            "proposed_name": body.proposed_name,
            "proposed_category": body.proposed_category,
            "socials": body.socials or {},
            "submitter_contact": body.submitter_contact,
            "note": body.note,
        },
    )
    if not row:
        raise HTTPException(status_code=500, detail="Submission could not be saved")
    return row
