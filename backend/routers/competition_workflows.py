from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel, ConfigDict

from competition_authz import require_operator, require_viewer_or_operator
from competition_runtime import (
    release_commit,
    slurm_probe_script,
    slurm_user,
    workflow_root,
)
from database import get_db
from models import User
from models_workflow import WorkflowAttempt, WorkflowRun, WorkflowStep
from schemas_workflow import DraftCreateRequest
from services.competition_inputs import InputValidationError, MAX_STRUCTURE_BYTES
from services.competition_reconcile import CompetitionReconciler, ReconcileError
from services.competition_slurm import SlurmClient
from services.competition_workflows import (
    WorkflowServiceError,
    confirm_workflow,
    create_draft,
    stage_structure,
)


router = APIRouter(prefix="/competition", tags=["competition-workflows"])

_EXECUTING_STATUSES = frozenset({"submitting", "queued", "running", "cancelling"})
_SUCCESS_STATUSES = frozenset({"succeeded"})
_ATTENTION_STATUSES = frozenset(
    {"failed", "validation_failed", "blocked", "submission_failed", "unknown"}
)


class CancellationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def get_competition_reconciler() -> CompetitionReconciler:
    root = workflow_root()
    script = slurm_probe_script()
    client = SlurmClient(
        workflow_root=root,
        allowed_scripts=(script,),
    )
    return CompetitionReconciler(
        slurm=client,
        probe_script=script,
        slurm_user=slurm_user(),
    )


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


def _latest_attempt(step: WorkflowStep) -> WorkflowAttempt | None:
    return max(step.attempts, key=lambda item: item.attempt_number, default=None)


def _relative_attempt_directory(
    workflow_id: str,
    attempt: WorkflowAttempt,
) -> str | None:
    if not attempt.working_directory:
        return None
    root = workflow_root().resolve()
    expected = root / workflow_id / "attempts" / attempt.id
    candidate = Path(attempt.working_directory)
    try:
        if candidate.resolve() != expected.resolve():
            return None
        return expected.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def _step_payload(step: WorkflowStep, workflow_id: str) -> dict[str, Any]:
    attempt = _latest_attempt(step)
    metadata = _metadata(attempt.metadata_json) if attempt is not None else {}
    observation = metadata.get("scheduler_observation", {})
    if not isinstance(observation, dict):
        observation = {}
    return {
        "key": step.step_key,
        "status": step.status,
        "job_id": attempt.slurm_job_id if attempt is not None else None,
        "attempt": attempt.attempt_number if attempt is not None else 0,
        "attempt_dir": (
            _relative_attempt_directory(workflow_id, attempt)
            if attempt is not None
            else None
        ),
        "slurm_state": observation.get("raw_state"),
        "exit_code": observation.get("exit_code"),
        "reason": observation.get("reason"),
        "accepted": attempt.slurm_job_id is not None if attempt is not None else None,
    }


def _list_item(run: WorkflowRun) -> dict[str, Any]:
    attempts = [
        (step, attempt)
        for step in run.steps
        if (attempt := _latest_attempt(step)) is not None
    ]
    latest = max(attempts, key=lambda item: item[1].updated_at, default=None)
    return {
        "id": run.id,
        "material": run.material,
        "source": _source_label(run.source_kind),
        "status": run.status,
        "current_step": latest[0].step_key if latest is not None else None,
        "latest_job_id": latest[1].slurm_job_id if latest is not None else None,
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
        "steps": [_step_payload(step, run.id) for step in steps],
        "created_at": _timestamp(run.created_at),
    }


def _visible_runs_statement(current_user: User):
    statement = select(WorkflowRun)
    if str(current_user.role).strip().lower() == "operator":
        statement = statement.where(WorkflowRun.owner_id == current_user.id)
    return statement


def _visible_attempts_statement(current_user: User):
    statement = (
        select(WorkflowAttempt.status, WorkflowAttempt.updated_at)
        .join(WorkflowStep, WorkflowAttempt.step_id == WorkflowStep.id)
        .join(WorkflowRun, WorkflowStep.workflow_id == WorkflowRun.id)
    )
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
            release_commit=release_commit(),
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
        statement.options(
            selectinload(WorkflowRun.steps).selectinload(WorkflowStep.attempts)
        )
        .order_by(WorkflowRun.updated_at.desc(), WorkflowRun.id)
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
        .options(
            selectinload(WorkflowRun.steps).selectinload(WorkflowStep.attempts),
            selectinload(WorkflowRun.owner),
        )
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
        statement.options(
            selectinload(WorkflowRun.steps).selectinload(WorkflowStep.attempts)
        )
        .order_by(WorkflowRun.updated_at.desc(), WorkflowRun.id)
        .limit(10)
    ).all()
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0

    def count_statuses(values: frozenset[str]) -> int:
        return db.scalar(
            select(func.count()).select_from(
                statement.where(WorkflowRun.status.in_(values)).subquery()
            )
        ) or 0

    attempt_rows = _visible_attempts_statement(current_user).subquery()
    queued = db.scalar(
        select(func.count()).select_from(attempt_rows).where(attempt_rows.c.status == "queued")
    ) or 0
    running = db.scalar(
        select(func.count())
        .select_from(attempt_rows)
        .where(attempt_rows.c.status.in_(("running", "cancelling")))
    ) or 0
    unknown = db.scalar(
        select(func.count()).select_from(attempt_rows).where(attempt_rows.c.status == "unknown")
    ) or 0
    attempt_total = db.scalar(select(func.count()).select_from(attempt_rows)) or 0
    scheduler_updated_at = db.scalar(select(func.max(attempt_rows.c.updated_at)))
    scheduler_state = (
        "unknown"
        if unknown
        else "running"
        if running
        else "queued"
        if queued
        else "idle"
    )
    active = next((run for run in rows if run.status in _EXECUTING_STATUSES), None)

    return {
        "summary": {
            "total": total,
            "running": count_statuses(_EXECUTING_STATUSES),
            "recent_succeeded": count_statuses(_SUCCESS_STATUSES),
            "needs_attention": count_statuses(_ATTENTION_STATUSES),
        },
        "recent_workflows": [_list_item(run) for run in rows],
        "active_workflow": _list_item(active) if active is not None else None,
        "slurm": {
            "partition": None,
            "queued": queued,
            "running": running,
            "state": scheduler_state,
            "updated_at": _timestamp(scheduler_updated_at),
            "attempts": attempt_total,
        },
        "data_kind": "live",
    }


def _raise_reconcile_error(exc: ReconcileError) -> None:
    responses = {
        "attempt_not_found": (status.HTTP_404_NOT_FOUND, "attempt was not found"),
        "job_not_active": (status.HTTP_409_CONFLICT, "attempt does not have an active job"),
        "cancellation_ownership_mismatch": (
            status.HTTP_409_CONFLICT,
            "scheduler ownership could not be verified",
        ),
        "cancellation_not_configured": (
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "scheduler service unavailable",
        ),
        "scheduler_unavailable": (
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "scheduler service unavailable",
        ),
        "cancellation_failed": (
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "scheduler service unavailable",
        ),
    }
    http_status, detail = responses.get(
        exc.code,
        (status.HTTP_409_CONFLICT, "cancellation could not be completed"),
    )
    raise HTTPException(
        status_code=http_status,
        detail=detail,
        headers={"X-Error-Code": exc.code},
    ) from None


@router.post("/workflows/{workflow_id}/attempts/{attempt_id}/cancel")
def cancel_attempt(
    workflow_id: str,
    attempt_id: str,
    _payload: CancellationRequest | None = None,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
    reconciler: CompetitionReconciler = Depends(get_competition_reconciler),
):
    run = db.scalar(
        _visible_runs_statement(current_user).where(WorkflowRun.id == workflow_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="workflow was not found")
    attempt = db.scalar(
        select(WorkflowAttempt)
        .join(WorkflowStep, WorkflowAttempt.step_id == WorkflowStep.id)
        .where(
            WorkflowAttempt.id == attempt_id,
            WorkflowStep.workflow_id == run.id,
        )
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="attempt was not found")
    try:
        result = reconciler.cancel_attempt(db, workflow_id, attempt_id)
    except ReconcileError as exc:
        _raise_reconcile_error(exc)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="scheduler service unavailable",
        ) from None
    return {
        "workflow_id": result.workflow_id,
        "attempt_id": result.attempt_id,
        "job_id": result.job_id,
        "status": result.status,
        "result": result.result,
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
