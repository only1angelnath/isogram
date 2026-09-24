"""
routes/projects.py — GET /projects, GET /projects/{project_id}

Read-only, per docs/AUDIT.md.
"""

from fastapi import APIRouter, Depends, HTTPException

from aggregate import build_all_summaries, build_project_summary, latest_score_by_project
from db import (
    fetch_all_latest_scores,
    fetch_latest_scores_for_project,
    fetch_project,
    fetch_projects,
    get_client,
)
from models import ProjectDetail, ProjectSummary

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSummary])
def list_projects(client=Depends(get_client)):
    """Every tracked project with its latest score, TVL, and gas figures."""
    projects = fetch_projects(client)
    scores = fetch_all_latest_scores(client)
    return build_all_summaries(projects, scores)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, client=Depends(get_client)):
    """One project's detail, including its known contract addresses."""
    project = fetch_project(client, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No tracked project '{project_id}'")

    scores = fetch_latest_scores_for_project(client, project_id)
    score_row = latest_score_by_project(scores).get(project_id)
    summary = build_project_summary(project, score_row)
    return {
        **summary,
        "contracts": project.get("contracts") or [],
        "created_at": project.get("created_at"),
    }
