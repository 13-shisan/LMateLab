from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from competition_authz import require_operator, require_viewer_or_operator
from database import get_db
from models import User
from models_competition_agent import AgentRun
from schemas_competition_agent import AgentRunCreate, AgentRunView, CuratedStructureBuildRequest
from services.competition_agent.catalog import list_templates
from services.competition_agent.service import approve_run, create_run, run_view
from services.competition_agent.structures import (
    StructureBuildError,
    build_structure,
    build_structure_bundle,
    list_structure_catalog,
)
from services.competition_agent.tools import AgentToolError


router = APIRouter(prefix="/competition/agent", tags=["competition-agent"])


def require_agent_enabled() -> None:
    if os.environ.get("LMATELAB_COMPETITION_AGENT_ENABLED", "0") != "1":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


@router.get("/templates", dependencies=[Depends(require_agent_enabled)])
def templates(_user: User = Depends(require_viewer_or_operator)):
    return {"items": list_templates()}


@router.get("/structures", dependencies=[Depends(require_agent_enabled)])
def structures(_user: User = Depends(require_viewer_or_operator)):
    return {"items": list_structure_catalog()}


def _structure_parameters(payload: CuratedStructureBuildRequest) -> dict[str, object]:
    return payload.model_dump(mode="python")


@router.post("/structures/build", dependencies=[Depends(require_agent_enabled)])
def build_curated_structure(
    payload: CuratedStructureBuildRequest,
    _user: User = Depends(require_operator),
):
    try:
        return build_structure(**_structure_parameters(payload))
    except StructureBuildError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/structures/bundle", dependencies=[Depends(require_agent_enabled)])
def download_curated_structure_bundle(
    payload: CuratedStructureBuildRequest,
    _user: User = Depends(require_operator),
):
    try:
        content = build_structure_bundle(**_structure_parameters(payload))
    except StructureBuildError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{payload.material_id}-vasp-inputs.zip"'
            )
        },
    )


@router.post(
    "/runs",
    response_model=AgentRunView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_agent_enabled)],
)
def create_agent_run(
    payload: AgentRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    try:
        return run_view(create_run(db, current_user.id, payload))
    except AgentToolError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from exc


def _visible_run(db: Session, run_id: str, user: User) -> AgentRun:
    query = select(AgentRun).where(AgentRun.id == run_id)
    if user.role == "operator":
        query = query.where(AgentRun.owner_id == user.id)
    else:
        query = query.where(AgentRun.approved_at.is_not(None))
    run = db.scalar(query)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return run


@router.get(
    "/runs/{run_id}",
    response_model=AgentRunView,
    dependencies=[Depends(require_agent_enabled)],
)
def get_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer_or_operator),
):
    return run_view(
        _visible_run(db, run_id, current_user),
        include_request=current_user.role == "operator",
    )


@router.get("/runs", dependencies=[Depends(require_agent_enabled)])
def list_agent_runs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer_or_operator),
):
    query = select(AgentRun)
    if current_user.role == "operator":
        query = query.where(AgentRun.owner_id == current_user.id)
    else:
        query = query.where(AgentRun.approved_at.is_not(None))
    rows = list(db.scalars(query.order_by(AgentRun.created_at.desc()).limit(50)))
    return {
        "items": [
            run_view(row, include_request=current_user.role == "operator")
            for row in rows
        ]
    }


@router.post(
    "/runs/{run_id}/approve",
    response_model=AgentRunView,
    dependencies=[Depends(require_agent_enabled)],
)
def approve_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    run = _visible_run(db, run_id, current_user)
    try:
        return run_view(approve_run(db, run, current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="run is not complete") from exc
