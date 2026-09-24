"""
routes/badge.py — GET /badge/{project_id}.svg

Embeddable README badge, per docs/PRD.md §4 (Arc Native Score + embeddable
badge). Renders a real SVG from the latest project_scores row, with an
honest "insufficient data" fallback for a project with no score yet
(docs/TESTING.md #4, docs/AUDIT.md). Read-only, per docs/AUDIT.md.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from aggregate import latest_score_by_project, render_badge_svg
from db import fetch_latest_scores_for_project, fetch_project, get_client

router = APIRouter(prefix="/badge", tags=["badge"])


@router.get("/{project_id}.svg")
def badge_svg(project_id: str, client=Depends(get_client)):
    project = fetch_project(client, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No tracked project '{project_id}'")

    scores = fetch_latest_scores_for_project(client, project_id)
    score_row = latest_score_by_project(scores).get(project_id)
    score_value = float(score_row["score"]) if score_row and score_row.get("score") is not None else None

    svg = render_badge_svg(project["name"], score_value)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "max-age=3600"},  # badges don't need to be live-live
    )
