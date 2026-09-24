"""
routes/gas.py — GET /gas/top, GET /gas/{project_id}

USDC gas figures come from the latest project_scores row (usdc_gas_7d), not
a live gas_events aggregation — see docs/ARCHITECTURE.md §2.3: the API reads
through Postgres, computed metrics are the scoring job's job, not this
layer's. Read-only, per docs/AUDIT.md.
"""

from fastapi import APIRouter, Depends, HTTPException

from aggregate import build_all_summaries, build_project_summary, latest_score_by_project, top_by_metric
from db import (
    fetch_all_latest_scores,
    fetch_latest_scores_for_project,
    fetch_project,
    fetch_projects,
    get_client,
)
from models import ProjectSummary

router = APIRouter(prefix="/gas", tags=["gas"])


@router.get("/top", response_model=list[ProjectSummary])
def top_gas(limit: int = 10, client=Depends(get_client)):
    """Top projects by trailing-7-day USDC gas paid, highest first."""
    projects = fetch_projects(client)
    scores = fetch_all_latest_scores(client)
    summaries = build_all_summaries(projects, scores)
    return top_by_metric(summaries, "usdc_gas_7d", limit)


@router.get("/{project_id}", response_model=ProjectSummary)
def gas_for_project(project_id: str, client=Depends(get_client)):
    """One project's trailing-7-day USDC gas figure."""
    project = fetch_project(client, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No tracked project '{project_id}'")

    scores = fetch_latest_scores_for_project(client, project_id)
    score_row = latest_score_by_project(scores).get(project_id)
    return build_project_summary(project, score_row)
