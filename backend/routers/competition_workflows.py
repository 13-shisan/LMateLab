from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
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
from models_workflow import WorkflowAttempt, WorkflowRun, WorkflowStep, canonical_json
from schemas_workflow import DraftCreateRequest, LogTailResponse
from services.competition_coordinator import CompetitionCoordinator
from services.competition_inputs import InputValidationError, MAX_STRUCTURE_BYTES
from services.competition_reconcile import CompetitionReconciler, ReconcileError
from services.competition_results import CompetitionResultService, ResultServiceError
from services.competition_slurm import SlurmClient, SlurmError
from services.competition_vasp import AcceptanceReport, VaspPolicyError
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
_SAFE_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_SAFE_SLURM_STATE = re.compile(r"[A-Z][A-Z0-9_+]{0,63}")
_SAFE_EXIT_CODE = re.compile(r"[0-9]+:[0-9]+")
_SAFE_JOB_ID = re.compile(r"[1-9][0-9]{0,99}")
_SAFE_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_LOG_TAIL_BYTES = 64 * 1024
_MAX_LOG_RESPONSE_OVERHEAD = 64


class EmptyCommandRequest(BaseModel):
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


def get_competition_coordinator(request: Request) -> CompetitionCoordinator:
    worker = getattr(request.app.state, "coordinator_worker", None)
    is_closed = getattr(worker, "is_closed", None)
    if worker is None or not callable(is_closed) or is_closed():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="workflow coordinator unavailable",
            headers={"X-Error-Code": "coordinator_unavailable"},
        )
    coordinator = getattr(worker, "coordinator", None)
    if coordinator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="workflow coordinator unavailable",
            headers={"X-Error-Code": "coordinator_unavailable"},
        )
    return coordinator


def get_competition_slurm_client(
    coordinator: CompetitionCoordinator = Depends(get_competition_coordinator),
) -> SlurmClient:
    reconciler = getattr(coordinator, "reconciler", None)
    client = getattr(reconciler, "slurm", None)
    if client is None or not callable(getattr(client, "read_log_tail", None)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="scheduler service unavailable",
            headers={"X-Error-Code": "scheduler_unavailable"},
        )
    return client


def get_competition_result_service() -> CompetitionResultService:
    return CompetitionResultService(workflow_root=workflow_root())


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


def _safe_iso_timestamp(value: object) -> str | None:
    if type(value) is not str or not value or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.isoformat()


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


def _safe_match(value: object, pattern: re.Pattern[str]) -> str | None:
    if type(value) is str and pattern.fullmatch(value) is not None:
        return value
    return None


def _safe_canonical_uuid(value: object) -> str | None:
    if type(value) is not str:
        return None
    try:
        return value if str(UUID(value)) == value else None
    except ValueError:
        return None


def _safe_acceptance(
    metadata: dict[str, Any],
    attempt_status: str,
) -> dict[str, Any] | None:
    value = metadata.get("scientific_acceptance")
    digest = _safe_match(metadata.get("scientific_acceptance_sha256"), _SAFE_SHA256)
    if not isinstance(value, dict) or digest is None:
        return None
    try:
        report = AcceptanceReport(
            accepted=value.get("accepted"),
            reason_code=value.get("reason_code"),
            checks=tuple(value.get("checks", ())),
            measurements=value.get("measurements", {}),
            artifacts=tuple(value.get("artifacts", ())),
        )
        result = report.as_dict()
        calculated = hashlib.sha256(
            canonical_json(result).encode("utf-8")
        ).hexdigest()
    except (AttributeError, TypeError, ValueError):
        return None
    expected_status = "succeeded" if report.accepted else "scientific_failed"
    if calculated != digest or attempt_status != expected_status:
        return None
    return result


def _step_payload(step: WorkflowStep, workflow_id: str) -> dict[str, Any]:
    attempt = _latest_attempt(step)
    metadata = _metadata(attempt.metadata_json) if attempt is not None else {}
    observation = metadata.get("scheduler_observation", {})
    if not isinstance(observation, dict):
        observation = {}
    acceptance = (
        _safe_acceptance(metadata, attempt.status)
        if attempt is not None
        else None
    )
    accepted = acceptance.get("accepted") if acceptance is not None else None
    reason = (
        acceptance.get("reason_code")
        if acceptance is not None
        else _safe_match(observation.get("error_code"), _SAFE_REASON_CODE)
    )
    resources = (
        dict(acceptance.get("measurements", {}))
        if acceptance is not None
        else {}
    )
    return {
        "key": step.step_key,
        "status": step.status,
        "job_id": (
            _safe_match(attempt.slurm_job_id, _SAFE_JOB_ID)
            if attempt is not None
            else None
        ),
        "attempt": attempt.attempt_number if attempt is not None else 0,
        "attempt_id": (
            _safe_canonical_uuid(attempt.id) if attempt is not None else None
        ),
        "attempt_dir": (
            _relative_attempt_directory(workflow_id, attempt)
            if attempt is not None
            else None
        ),
        "slurm_state": _safe_match(observation.get("raw_state"), _SAFE_SLURM_STATE),
        "exit_code": _safe_match(observation.get("exit_code"), _SAFE_EXIT_CODE),
        "scheduler_stale": observation.get("stale") is True,
        "stale_since": _safe_iso_timestamp(observation.get("stale_since")),
        "reason": reason,
        "accepted": accepted,
        "acceptance": acceptance,
        "resources": resources,
        "updated_at": _timestamp(
            attempt.updated_at if attempt is not None else step.updated_at
        ),
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
        "latest_job_id": (
            _safe_match(latest[1].slurm_job_id, _SAFE_JOB_ID)
            if latest is not None
            else None
        ),
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


def _raise_input_error(exc: InputValidationError) -> None:
    message = str(exc).lower()
    rules = (
        (("1 mib",), "structure_file_too_large", "结构文件超过 1 MiB 限制"),
        (("200 atoms", "exceeds 200 atoms"), "structure_atom_limit", "结构超过 200 个原子限制"),
        (("filename", "path components"), "structure_filename_invalid", "结构文件名不符合安全要求"),
        (("element", "potcar"), "structure_elements_invalid", "结构元素或元素顺序无效"),
        (("periodic", "cell", "positions", "geometry"), "structure_geometry_invalid", "结构晶格或原子坐标无效"),
        (("utf-8", "binary", "empty"), "structure_content_invalid", "结构文件必须是非空 UTF-8 文本"),
        (("parsed as vasp or cif", "missing the element header"), "structure_format_invalid", "无法按 POSCAR 或 CIF 解析结构"),
        (("template", "uploaded structure"), "workflow_template_invalid", "结构来源与计算模板不匹配"),
    )
    code = "workflow_input_invalid"
    detail = "请求内容未通过工作流校验"
    for terms, candidate_code, candidate_detail in rules:
        if any(term in message for term in terms):
            code = candidate_code
            detail = candidate_detail
            break
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
        headers={"X-Error-Code": code},
    ) from None


def _raise_command_error(exc: Exception) -> None:
    if isinstance(exc, SlurmError):
        code = "scheduler_unavailable"
    elif isinstance(exc, InputValidationError):
        code = "workflow_input_invalid"
    else:
        code = _safe_match(getattr(exc, "code", None), _SAFE_REASON_CODE)
        if code is None:
            code = "workflow_command_unavailable"

    if code == "workflow_not_found":
        http_status = status.HTTP_404_NOT_FOUND
        detail = "workflow was not found"
    elif isinstance(exc, VaspPolicyError) or code in {
        "workflow_step_invalid",
        "invalid_step",
        "workflow_scope_invalid",
        "workflow_input_invalid",
    }:
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = "workflow command was rejected"
    elif code in {
        "scheduler_unavailable",
        "submission_failed",
        "cancellation_failed",
        "cancellation_not_configured",
        "workflow_command_unavailable",
    }:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
        detail = "scheduler service unavailable"
    else:
        http_status = status.HTTP_409_CONFLICT
        detail = "workflow command conflicts with current state"
    raise HTTPException(
        status_code=http_status,
        detail=detail,
        headers={"X-Error-Code": code},
    ) from None


def _command_payload(outcome: Any) -> dict[str, Any]:
    return {
        "workflow_id": str(outcome.workflow_id),
        "attempt_id": str(outcome.attempt_id),
        "step_key": str(outcome.step_key),
        "status": str(outcome.status),
    }


def _cancellation_payload(outcome: Any) -> dict[str, Any]:
    return {
        "workflow_id": str(outcome.workflow_id),
        "attempt_id": str(outcome.attempt_id),
        "job_id": str(outcome.job_id),
        "status": str(outcome.status),
        "result": str(outcome.result),
    }


def _visible_attempt_statement(
    current_user: User,
    workflow_id: str,
    attempt_id: str,
):
    statement = (
        select(WorkflowAttempt)
        .join(WorkflowStep, WorkflowAttempt.step_id == WorkflowStep.id)
        .join(WorkflowRun, WorkflowStep.workflow_id == WorkflowRun.id)
        .where(
            WorkflowAttempt.id == attempt_id,
            WorkflowStep.workflow_id == workflow_id,
            WorkflowRun.id == workflow_id,
        )
    )
    if str(current_user.role).strip().lower() == "operator":
        statement = statement.where(WorkflowRun.owner_id == current_user.id)
    return statement


def _bounded_log_content(stream: str, content: str) -> str:
    if not isinstance(content, str):
        raise TypeError("log content must be text")
    maximum_response_bytes = _MAX_LOG_TAIL_BYTES + _MAX_LOG_RESPONSE_OVERHEAD

    def response_size(value: str) -> int:
        return len(
            json.dumps(
                {"stream": stream, "content": value},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    if response_size(content) <= maximum_response_bytes:
        return content
    low = 0
    high = len(content)
    while low < high:
        middle = (low + high) // 2
        if response_size(content[middle:]) <= maximum_response_bytes:
            high = middle
        else:
            low = middle + 1
    return content[low:]


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
        _raise_input_error(exc)
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
        _raise_input_error(exc)
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
        _raise_input_error(exc)
    except Exception:
        raise HTTPException(status_code=500, detail="workflow service unavailable") from None
    return result.model_dump(mode="json")


@router.post("/workflows/{workflow_id}/start")
def start_workflow(
    workflow_id: UUID,
    _payload: EmptyCommandRequest | None = None,
    current_user: User = Depends(require_operator),
    coordinator: CompetitionCoordinator = Depends(get_competition_coordinator),
):
    try:
        outcome = coordinator.start(str(workflow_id), current_user.id)
        return _command_payload(outcome)
    except Exception as exc:
        _raise_command_error(exc)


@router.post("/workflows/{workflow_id}/steps/{step_key}/retry")
def retry_workflow_step(
    workflow_id: UUID,
    step_key: Literal["relax", "scf", "band", "dos"],
    _payload: EmptyCommandRequest | None = None,
    current_user: User = Depends(require_operator),
    coordinator: CompetitionCoordinator = Depends(get_competition_coordinator),
):
    try:
        outcome = coordinator.retry(str(workflow_id), current_user.id, step_key)
        return _command_payload(outcome)
    except Exception as exc:
        _raise_command_error(exc)


@router.post("/workflows/{workflow_id}/cancel")
def cancel_workflow(
    workflow_id: UUID,
    _payload: EmptyCommandRequest | None = None,
    current_user: User = Depends(require_operator),
    coordinator: CompetitionCoordinator = Depends(get_competition_coordinator),
):
    try:
        outcome = coordinator.cancel(str(workflow_id), current_user.id)
        return _cancellation_payload(outcome)
    except Exception as exc:
        _raise_command_error(exc)


@router.get(
    "/workflows/{workflow_id}/attempts/{attempt_id}/logs/{stream}",
    response_model=LogTailResponse,
)
def read_attempt_log(
    request: Request,
    workflow_id: UUID,
    attempt_id: UUID,
    stream: Literal["stdout", "stderr"],
    current_user: User = Depends(require_viewer_or_operator),
    db: Session = Depends(get_db),
    slurm_client: SlurmClient = Depends(get_competition_slurm_client),
):
    content_length = request.headers.get("content-length")
    if (
        request.query_params
        or request.headers.get("transfer-encoding") is not None
        or content_length not in {None, "0"}
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="log request does not accept overrides",
            headers={"X-Error-Code": "log_request_invalid"},
        )
    canonical_workflow_id = str(workflow_id)
    canonical_attempt_id = str(attempt_id)
    attempt = db.scalar(
        _visible_attempt_statement(
            current_user,
            canonical_workflow_id,
            canonical_attempt_id,
        )
    )
    if attempt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="workflow attempt was not found",
            headers={"X-Error-Code": "attempt_not_found"},
        )
    try:
        content = slurm_client.read_log_tail(
            canonical_workflow_id,
            canonical_attempt_id,
            stream,
        )
        return LogTailResponse(
            stream=stream,
            content=_bounded_log_content(stream, content),
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="log could not be read safely",
            headers={"X-Error-Code": "log_read_unsafe"},
        ) from None
    except SlurmError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="scheduler service unavailable",
            headers={"X-Error-Code": "scheduler_unavailable"},
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="log service unavailable",
            headers={"X-Error-Code": "log_service_unavailable"},
        ) from None


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
    _payload: EmptyCommandRequest | None = None,
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
    current_user: User = Depends(require_viewer_or_operator),
    db: Session = Depends(get_db),
    service: CompetitionResultService = Depends(get_competition_result_service),
):
    requested_status = (status_filter or "all").strip().lower()
    if requested_status not in {"all", "succeeded", "failed", "parse-error"}:
        raise HTTPException(status_code=400, detail="result status is invalid")
    statement = (
        _visible_runs_statement(current_user)
        .where(WorkflowRun.status.in_(("succeeded", "failed")))
        .options(
            selectinload(WorkflowRun.owner),
            selectinload(WorkflowRun.steps).selectinload(WorkflowStep.attempts),
            selectinload(WorkflowRun.files),
            selectinload(WorkflowRun.events),
        )
        .order_by(WorkflowRun.updated_at.desc(), WorkflowRun.id)
    )
    items = [service.summary(run) for run in db.scalars(statement).unique().all()]
    needle = query.strip().casefold()
    if needle:
        items = [
            item
            for item in items
            if needle
            in " ".join(
                str(item.get(key) or "")
                for key in ("material", "source", "workflow_id")
            ).casefold()
        ]
    if requested_status != "all":
        items = [item for item in items if item.get("status") == requested_status]
    return {"items": items, "total": len(items), "data_kind": "live"}


def _result_run(
    db: Session,
    current_user: User,
    workflow_id: str,
) -> WorkflowRun:
    run = db.scalar(
        _visible_runs_statement(current_user)
        .where(
            WorkflowRun.id == workflow_id,
            WorkflowRun.status.in_(("succeeded", "failed")),
        )
        .options(
            selectinload(WorkflowRun.owner),
            selectinload(WorkflowRun.steps).selectinload(WorkflowStep.attempts),
            selectinload(WorkflowRun.files),
            selectinload(WorkflowRun.events),
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="result was not found")
    return run


def _raise_result_error(exc: ResultServiceError) -> None:
    if exc.code in {"artifact_kind_invalid", "plot_kind_invalid"}:
        http_status = status.HTTP_400_BAD_REQUEST
        detail = "result artifact request is invalid"
    elif exc.code == "result_not_terminal":
        http_status = status.HTTP_409_CONFLICT
        detail = "workflow result is not terminal"
    elif exc.code in {"artifact_unavailable", "artifact_missing"}:
        http_status = status.HTTP_409_CONFLICT
        detail = "result artifact is unavailable"
    else:
        http_status = status.HTTP_409_CONFLICT
        detail = "result evidence could not be verified"
    raise HTTPException(
        status_code=http_status,
        detail=detail,
        headers={"X-Error-Code": exc.code},
    ) from None


@router.get("/results/{workflow_id}")
def get_result(
    workflow_id: str,
    current_user: User = Depends(require_viewer_or_operator),
    db: Session = Depends(get_db),
    service: CompetitionResultService = Depends(get_competition_result_service),
):
    return service.detail(_result_run(db, current_user, workflow_id))


@router.get("/results/{workflow_id}/{kind}-plot")
def get_result_plot(
    workflow_id: str,
    kind: Literal["band", "dos"],
    current_user: User = Depends(require_viewer_or_operator),
    db: Session = Depends(get_db),
    service: CompetitionResultService = Depends(get_competition_result_service),
):
    run = _result_run(db, current_user, workflow_id)
    try:
        return service.plot(run, kind)
    except ResultServiceError as exc:
        _raise_result_error(exc)


@router.get("/results/{workflow_id}/artifacts/{kind}")
def download_result_artifact(
    workflow_id: str,
    kind: str,
    current_user: User = Depends(require_viewer_or_operator),
    db: Session = Depends(get_db),
    service: CompetitionResultService = Depends(get_competition_result_service),
):
    run = _result_run(db, current_user, workflow_id)
    try:
        artifact = service.artifact(db, run, kind)
    except ResultServiceError as exc:
        _raise_result_error(exc)
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/vasp/records")
def list_vasp_records(
    query: str = Query("", max_length=100),
    elements: str = Query("", max_length=200),
    element_mode: str = Query("", max_length=20),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_viewer_or_operator),
    db: Session = Depends(get_db),
    service: CompetitionResultService = Depends(get_competition_result_service),
):
    mode = (element_mode or "at_least").strip().lower()
    if mode not in {"at_least", "only"}:
        raise HTTPException(status_code=400, detail="element mode is invalid")
    requested_elements = [item.strip() for item in elements.split(",") if item.strip()]
    if len(requested_elements) != len(set(requested_elements)) or any(
        re.fullmatch(r"[A-Z][a-z]?", item) is None for item in requested_elements
    ):
        raise HTTPException(status_code=400, detail="element filter is invalid")
    statement = (
        _visible_runs_statement(current_user)
        .where(WorkflowRun.status.in_(("succeeded", "failed")))
        .options(
            selectinload(WorkflowRun.owner),
            selectinload(WorkflowRun.steps).selectinload(WorkflowStep.attempts),
            selectinload(WorkflowRun.files),
            selectinload(WorkflowRun.events),
        )
        .order_by(WorkflowRun.updated_at.desc(), WorkflowRun.id)
    )
    records = [service.database_record(run) for run in db.scalars(statement).unique().all()]
    available_elements = sorted(
        {element for record in records for element in record.get("elements", [])}
    )
    needle = query.strip().casefold()
    if needle:
        records = [
            record
            for record in records
            if needle
            in " ".join(
                str(record.get(key) or "")
                for key in ("formula", "source", "workflow_id")
            ).casefold()
        ]
    required = set(requested_elements)
    if required:
        records = [
            record
            for record in records
            if (
                set(record.get("elements", [])) == required
                if mode == "only"
                else required.issubset(set(record.get("elements", [])))
            )
        ]
    total = len(records)
    start = (page - 1) * page_size
    return {
        "items": records[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "available_elements": available_elements,
        "metadata": {
            "source": {"label": "来源", "kind": "text", "priority": 1},
            "workflow_id": {"label": "工作流", "kind": "text", "priority": 1},
            "status": {"label": "状态", "kind": "text", "priority": 1},
            "bandgap_eV": {
                "label": "带隙",
                "unit": "eV",
                "decimals": 4,
                "kind": "number",
                "priority": 1,
            },
            "completed_at": {"label": "完成时间", "kind": "text", "priority": 2},
        },
        "data_kind": "live",
    }


@router.get("/vasp/records/{workflow_id}")
def get_vasp_record(
    workflow_id: str,
    current_user: User = Depends(require_viewer_or_operator),
    db: Session = Depends(get_db),
    service: CompetitionResultService = Depends(get_competition_result_service),
):
    return service.database_record(_result_run(db, current_user, workflow_id))
