from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from competition_authz import require_operator, require_viewer_or_operator
from competition_runtime import workflow_root
from database import get_db
from models import User
from models_workflow import WorkflowRun, WorkflowStep
from schemas_workflow import DraftCreateRequest
from services.competition_inputs import InputValidationError, MAX_STRUCTURE_BYTES
from services.competition_workflows import (
    WorkflowServiceError,
    confirm_workflow,
    create_draft,
    stage_structure,
)


router = APIRouter(prefix="/competition", tags=["competition-workflows"])

_EXECUTING_STATUSES = frozenset({"queued", "running"})
_SUCCESS_STATUSES = frozenset({"succeeded"})
_ATTENTION_STATUSES = frozenset({"failed", "validation_failed", "blocked"})


def _metadata(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _source_label(source_kind: str) -> str:
    return "uploaded structure" if source_kind == "upload" else "built-in MoS2"


def _step_payload(step: WorkflowStep) -> dict[str, Any]:
    return {
        "key": step.step_key,
        "status": step.status,
        "job_id": None,
        "attempt": 0,
        "attempt_dir": None,
        "slurm_state": None,
        "exit_code": None,
        "reason": None,
        "accepted": None,
    }


def _list_item(run: WorkflowRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "material": run.material,
        "source": _source_label(run.source_kind),
        "status": run.status,
        "current_step": None,
        "latest_job_id": None,
        "updated_at": _timestamp(run.updated_at),
        "data_kind": "live",
    }


def _detail(run: WorkflowRun) -> dict[str, Any]:
    metadata = _metadata(run.metadata_json)
    steps = sorted(run.steps, key=lambda item: item.position)
    return {
        **_list_item(run),
        "creator": run.owner.alias or run.owner.name,
        "template_version": run.template_version,
        "input_sha256": run.input_sha256,
        "release_commit": run.release_commit,
        "structure_summary": metadata.get("structure_summary", {}),
        "steps": [_step_payload(step) for step in steps],
        "created_at": _timestamp(run.created_at),
    }


def _visible_runs_statement(current_user: User):
    statement = select(WorkflowRun)
    if str(current_user.role).strip().lower() == "operator":
        statement = statement.where(WorkflowRun.owner_id == current_user.id)
    return statement


def _raise_service_error(exc: WorkflowServiceError) -> None:
    if exc.code == "workflow_not_found":
        http_status = status.HTTP_404_NOT_FOUND
    elif exc.code in {"workflow_not_confirmable", "execution_state_exists"}:
        http_status = status.HTTP_409_CONFLICT
    elif exc.code == "upload_unavailable":
        http_status = status.HTTP_404_NOT_FOUND
    else:
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(
        status_code=http_status,
        detail=str(exc),
        headers={"X-Error-Code": exc.code},
    ) from None


@router.post("/structures", status_code=status.HTTP_201_CREATED)
async def upload_structure(
    file: UploadFile = File(...),
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        content = await file.read(MAX_STRUCTURE_BYTES + 1)
        if len(content) > MAX_STRUCTURE_BYTES:
            raise InputValidationError("structure file exceeds 1 MiB limit")
        result = stage_structure(
            db,
            workflow_root(),
            owner_id=current_user.id,
            content=content,
            filename=file.filename or "",
        )
    except InputValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except WorkflowServiceError as exc:
        _raise_service_error(exc)
    except Exception:
        raise HTTPException(status_code=500, detail="workflow service unavailable") from None
    finally:
        await file.close()
    return {
        "id": result.id,
        "size_bytes": result.size_bytes,
        "sha256": result.sha256,
        "source_format": result.source_format,
        "summary": result.summary,
    }


@router.post("/drafts", status_code=status.HTTP_201_CREATED)
def save_draft(
    payload: DraftCreateRequest,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        result = create_draft(
            db,
            workflow_root(),
            owner_id=current_user.id,
            payload=payload,
        )
    except InputValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except WorkflowServiceError as exc:
        _raise_service_error(exc)
    except Exception:
        raise HTTPException(status_code=500, detail="workflow service unavailable") from None
    return result.model_dump(mode="json")


@router.post("/workflows/{workflow_id}/submit")
def submit_workflow(
    workflow_id: str,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    try:
        result = confirm_workflow(
            db,
            workflow_root(),
            owner_id=current_user.id,
            workflow_id=workflow_id,
        )
    except (InputValidationError, WorkflowServiceError) as exc:
        if isinstance(exc, WorkflowServiceError):
            _raise_service_error(exc)
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        raise HTTPException(status_code=500, detail="workflow service unavailable") from None
    return result.model_dump(mode="json")


@router.get("/workflows")
def list_workflows(
    query: str = Query("", max_length=100),
    status_filter: str = Query("", alias="status", max_length=50),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_viewer_or_operator),
    db: Session = Depends(get_db),
):
    statement = _visible_runs_statement(current_user)
    normalized_query = query.strip()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        statement = statement.where(
            or_(
                WorkflowRun.id.like(pattern),
                WorkflowRun.material.like(pattern),
                WorkflowRun.source_kind.like(pattern),
            )
        )
    normalized_status = status_filter.strip().lower()
    if normalized_status and normalized_status != "all":
        statement = statement.where(WorkflowRun.status == normalized_status)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(
        statement.order_by(WorkflowRun.updated_at.desc(), WorkflowRun.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_list_item(run) for run in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "data_kind": "live",
    }


@router.get("/workflows/{workflow_id}")
def get_workflow(
    workflow_id: str,
    current_user: User = Depends(require_viewer_or_operator),
    db: Session = Depends(get_db),
):
    statement = (
        _visible_runs_statement(current_user)
        .where(WorkflowRun.id == workflow_id)
        .options(selectinload(WorkflowRun.steps), selectinload(WorkflowRun.owner))
    )
    run = db.scalar(statement)
    if run is None:
        raise HTTPException(status_code=404, detail="workflow was not found")
    return _detail(run)


@router.get("/dashboard")
def dashboard(
    current_user: User = Depends(require_viewer_or_operator),
    db: Session = Depends(get_db),
):
    statement = _visible_runs_statement(current_user)
    rows = db.scalars(
        statement.order_by(WorkflowRun.updated_at.desc(), WorkflowRun.id).limit(10)
    ).all()
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0

    def count_statuses(values: frozenset[str]) -> int:
        return db.scalar(
            select(func.count()).select_from(
                statement.where(WorkflowRun.status.in_(values)).subquery()
            )
        ) or 0

    return {
        "summary": {
            "total": total,
            "running": count_statuses(_EXECUTING_STATUSES),
            "recent_succeeded": count_statuses(_SUCCESS_STATUSES),
            "needs_attention": count_statuses(_ATTENTION_STATUSES),
        },
        "recent_workflows": [_list_item(run) for run in rows],
        "active_workflow": None,
        "slurm": {
            "partition": None,
            "queued": 0,
            "running": 0,
            "state": "not-integrated",
            "updated_at": None,
        },
        "data_kind": "live",
    }


@router.get("/results")
def list_results(
    query: str = Query("", max_length=100),
    status_filter: str = Query("", alias="status", max_length=50),
    _current_user: User = Depends(require_viewer_or_operator),
):
    return {"items": [], "total": 0, "data_kind": "live"}


@router.get("/vasp/records")
def list_vasp_records(
    query: str = Query("", max_length=100),
    elements: str = Query("", max_length=200),
    element_mode: str = Query("", max_length=20),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _current_user: User = Depends(require_viewer_or_operator),
):
    return {
        "items": [],
        "total": 0,
        "page": page,
        "page_size": page_size,
        "available_elements": [],
        "metadata": {},
        "data_kind": "live",
    }
