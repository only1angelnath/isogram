"""
routes/projects.py — GET /projects, GET /projects/{project_id}, GET /projects/by-address/{address}

Read-only, per docs/AUDIT.md.
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aggregate import build_all_summaries, build_project_summary, latest_score_by_project, primary_contract
from db import (
    fetch_all_latest_scores,
    fetch_holders,
    fetch_holders_for_address,
    fetch_socials,
    fetch_socials_for_address,
    fetch_latest_scores_for_project,
    fetch_market_data,
    fetch_market_for_address,
    fetch_project,
    fetch_project_ref_by_address,
    fetch_projects,
    get_client,
)
from models import ProjectDetail, ProjectSummary

router = APIRouter(prefix="/projects", tags=["projects"])
log = logging.getLogger("isogram.projects")


def _market_rows(client) -> list[dict]:
    """Market data is optional garnish: if its table is unreachable the project list must
    still load, just without prices."""
    try:
        return fetch_market_data(client)
    except Exception:
        log.exception("market data unavailable; serving projects without it")
        return []


def _holders_rows(client) -> list[dict]:
    """Holder counts are optional garnish too: never let their table take /projects down."""
    try:
        return fetch_holders(client)
    except Exception:
        log.exception("holder counts unavailable; serving projects without them")
        return []


def _holders_row(client, project: dict):
    address = primary_contract(project)
    if not address:
        return None
    try:
        return fetch_holders_for_address(client, address)
    except Exception:
        log.exception("holder count unavailable for %s", address)
        return None


def _socials_rows(client) -> list[dict]:
    """Self-reported links are optional garnish: never let their table take /projects down."""
    try:
        return fetch_socials(client)
    except Exception:
        log.exception("social links unavailable; serving projects without them")
        return []


def _socials_row(client, project: dict):
    address = primary_contract(project)
    if not address:
        return None
    try:
        return fetch_socials_for_address(client, address)
    except Exception:
        log.exception("social links unavailable for %s", address)
        return None


def _market_row(client, project: dict):
    address = primary_contract(project)
    if not address:
        return None
    try:
        return fetch_market_for_address(client, address)
    except Exception:
        log.exception("market data unavailable for %s", address)
        return None


@router.get("", response_model=list[ProjectSummary])
def list_projects(client=Depends(get_client)):
    """Every tracked project with its latest score, TVL, and gas figures (plus third-party
    market data for token and stablecoin projects)."""
    projects = fetch_projects(client)
    scores = fetch_all_latest_scores(client)
    return build_all_summaries(projects, scores, _market_rows(client), holders_rows=_holders_rows(client),
                               socials_rows=_socials_rows(client))


class ProjectRef(BaseModel):
    id: str
    name: str


_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


@router.get("/by-address/{address}", response_model=ProjectRef)
def get_project_by_address(address: str, client=Depends(get_client)):
    """Which tracked project owns this contract address (used by the dashboard's search box)."""
    if not _ADDRESS_RE.match(address):
        raise HTTPException(status_code=400, detail="Not a valid 0x address")
    ref = fetch_project_ref_by_address(client, address)
    if ref is None:
        raise HTTPException(status_code=404, detail="No tracked project has this contract")
    return {"id": ref["id"], "name": ref["name"]}


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, client=Depends(get_client)):
    """One project's detail, including its known contract addresses."""
    project = fetch_project(client, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No tracked project '{project_id}'")

    scores = fetch_latest_scores_for_project(client, project_id)
    score_row = latest_score_by_project(scores).get(project_id)
    summary = build_project_summary(project, score_row, _market_row(client, project),
                                    holders_row=_holders_row(client, project),
                                    socials_row=_socials_row(client, project))
    return {
        **summary,
        "contracts": project.get("contracts") or [],
        "created_at": project.get("created_at"),
    }


