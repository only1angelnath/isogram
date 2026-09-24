"""
routes/scores.py — GET /scores/top, GET /scores/{project_id}

The Arc Native Score itself (see docs/SCHEMA.md formula, computed by
scoring/compute_scores.py). Read-only, per docs/AUDIT.md.
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

router = APIRouter(prefix="/scores", tags=["scores"])


@router.get("/top", response_model=list[ProjectSummary])
def top_scores(limit: int = 10, client=Depends(get_client)):
    """Top projects by Arc Native Score, highest first."""
    projects = fetch_projects(client)
    scores = fetch_all_latest_scores(client)
    summaries = build_all_summaries(projects, scores)
    return top_by_metric(summaries, "score", limit)


@router.get("/{project_id}", response_model=ProjectSummary)
def score_for_project(project_id: str, client=Depends(get_client)):
    """One project's current Arc Native Score and its components."""
    project = fetch_project(client, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No tracked project '{project_id}'")

    scores = fetch_latest_scores_for_project(client, project_id)
    score_row = latest_score_by_project(scores).get(project_id)
    return build_project_summary(project, score_row)
