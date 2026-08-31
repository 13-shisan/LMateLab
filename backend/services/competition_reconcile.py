from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from models_workflow import (
    WorkflowAttempt,
    WorkflowRun,
    WorkflowStep,
    canonical_json,
)
from services.competition_slurm import (
    FIXED_STEPS,
    PROBE_MODES,
    RUNNER_MODES,
    SlurmClient,
    SlurmError,
    SlurmJobObservation,
    SlurmSubmission,
)
from services.competition_workflows import append_workflow_event


class ReconcileError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AttemptClaim:
    workflow_id: str
    step_id: int
    attempt_id: str
    submission: SlurmSubmission
    status: str
    execution_scope_v1_sha256: str | None = None


@dataclass(frozen=True)
class _AttemptRunnerContract:
    submission: SlurmSubmission
    expected_comment: str
    legacy: bool
    execution_scope_v1_sha256: str | None


@dataclass(frozen=True)
class SubmissionOutcome:
    workflow_id: str
    attempt_id: str
    job_id: str
    status: str


@dataclass(frozen=True)
class CancellationOutcome:
    workflow_id: str
    attempt_id: str | None
    job_id: str | None
    status: str
    result: str


@dataclass(frozen=True)
class ReconciliationOutcome:
    workflow_id: str
    attempt_id: str
    job_id: str
    raw_state: str | None
    status: str
    stale: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_ACTIVE_ATTEMPT_STATUSES = frozenset(
    {
        "preparing",
        "submitting",
        "queued",
        "running",
        "awaiting_acceptance",
        "cancelling",
    }
)
_RETRY_BLOCKING_ATTEMPT_STATUSES = _ACTIVE_ATTEMPT_STATUSES | {"unknown"}
RETRYABLE_ATTEMPT_STATUSES = frozenset(
    {"failed", "scientific_failed", "cancelled"}
)
_NEW_RUNNER_METADATA_FIELDS = frozenset(
    {"runner_kind", "runner_mode", "script_path", "script_sha256"}
)
_LEGACY_PROBE_METADATA_FIELDS = frozenset(
    {
        "before_cancel",
        "cancel_result",
        "comment",
        "job_name",
        "probe_mode",
        "scheduler_observation",
    }
)
_EXECUTION_SCOPE_METADATA_KEY = "execution_scope_v1_sha256"


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        type(value) is str
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _execution_scope_v1_sha256(run: WorkflowRun) -> str:
    try:
        metadata = json.loads(run.metadata_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReconcileError(
            "invalid_execution_scope",
            "workflow execution scope is invalid",
        ) from exc
    normalized = metadata.get("normalized_payload") if isinstance(metadata, dict) else None
    values = (
        run.template_version,
        run.material,
        run.source_kind,
        run.input_sha256,
        run.release_commit,
    )
    if (
        not isinstance(normalized, dict)
        or any(type(value) is not str or not value for value in values)
        or not _is_lower_hex(run.input_sha256, 64)
        or not _is_lower_hex(run.release_commit, 40)
    ):
        raise ReconcileError(
            "invalid_execution_scope",
            "workflow execution scope is invalid",
        )
    identity = {
        "version": 1,
        "template_version": run.template_version,
        "material": run.material,
        "source_kind": run.source_kind,
        "input_sha256": run.input_sha256,
        "release_commit": run.release_commit,
        "metadata": metadata,
    }
    return hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()


def _execution_scope_matches(
    run: WorkflowRun | None,
    expected_sha256: str,
) -> bool:
    if run is None:
        return False
    try:
        return _execution_scope_v1_sha256(run) == expected_sha256
    except ReconcileError:
        return False


class CompetitionReconciler:
    def __init__(
        self,
        *,
        slurm: SlurmClient,
        probe_script: Path,
        vasp_script: Path | None = None,
        clock: Callable[[], datetime] = _utc_now,
        slurm_user: str | None = None,
    ) -> None:
        self.slurm = slurm
        self.probe_script = Path(probe_script).resolve()
        self.vasp_script = Path(vasp_script).resolve() if vasp_script is not None else None
        self._runner_scripts = {"probe": self.probe_script}
        if self.vasp_script is not None:
            self._runner_scripts["vasp"] = self.vasp_script
        self._clock = clock
        self.slurm_user = slurm_user

    def _validated_runner_script(
        self,
        *,
        step_key: str,
        runner_kind: str,
        runner_mode: str,
        script_path: Path,
    ) -> Path:
        if step_key not in FIXED_STEPS:
            raise ReconcileError("invalid_step", "step is not part of the fixed workflow")
        if (
            runner_mode not in RUNNER_MODES.get(runner_kind, frozenset())
            or (runner_kind == "probe" and step_key != "relax")
            or (runner_kind == "vasp" and runner_mode != step_key)
        ):
            raise ReconcileError(
                "invalid_runner_contract",
                "runner contract is not allowed",
            )
        expected_script = self._runner_scripts.get(runner_kind)
        try:
            resolved_script = Path(script_path).resolve()
        except (OSError, TypeError, ValueError) as exc:
            raise ReconcileError(
                "invalid_runner_contract",
                "runner contract is not allowed",
            ) from exc
        if expected_script is None or resolved_script != expected_script:
            raise ReconcileError(
                "invalid_runner_contract",
                "runner contract is not allowed",
            )
        return expected_script

    def _unpublished_vasp_attempt_directory(
        self,
        workflow_id: str,
        attempt_id: str,
    ) -> Path:
        workflow_root = getattr(self.slurm, "workflow_root", None)
        if workflow_root is None:
            raise ReconcileError(
                "invalid_runner_contract",
                "VASP runner requires a workflow filesystem root",
            )
        root = Path(workflow_root).resolve()
        candidate = root / workflow_id / "attempts" / attempt_id
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ReconcileError(
                "invalid_runner_contract",
                "VASP attempt directory is invalid",
            ) from exc
        if not resolved.is_relative_to(root):
            raise ReconcileError(
                "invalid_runner_contract",
                "VASP attempt directory is invalid",
            )
        for parent in (root, root / workflow_id, root / workflow_id / "attempts"):
            if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
                raise ReconcileError(
                    "invalid_runner_contract",
                    "VASP attempt directory is invalid",
                )
        if candidate.exists() or candidate.is_symlink():
            raise ReconcileError(
                "attempt_directory_exists",
                "VASP attempt directory is already published",
            )
        return candidate

    def _runner_contract_from_metadata(
        self,
        *,
        run: WorkflowRun,
        step: WorkflowStep,
        attempt: WorkflowAttempt,
        metadata: dict[str, object],
    ) -> _AttemptRunnerContract:
        new_fields = _NEW_RUNNER_METADATA_FIELDS.intersection(metadata)
        has_legacy_mode = "probe_mode" in metadata
        if new_fields and has_legacy_mode:
            raise ReconcileError(
                "invalid_runner_contract",
                "runner contract is not allowed",
            )

        legacy = not new_fields and has_legacy_mode
        if legacy:
            if (
                step.step_key != "relax"
                or not set(metadata).issubset(_LEGACY_PROBE_METADATA_FIELDS)
                or metadata.get("probe_mode") not in PROBE_MODES
            ):
                raise ReconcileError(
                    "invalid_runner_contract",
                    "runner contract is not allowed",
                )
            runner_kind = "probe"
            runner_mode = metadata["probe_mode"]
            resolved_script = self.probe_script
        else:
            if new_fields != _NEW_RUNNER_METADATA_FIELDS:
                raise ReconcileError(
                    "invalid_runner_contract",
                    "runner contract is not allowed",
                )
            runner_kind = metadata.get("runner_kind")
            runner_mode = metadata.get("runner_mode")
            script_path = metadata.get("script_path")
            script_sha256 = metadata.get("script_sha256")
            if not all(
                isinstance(value, str)
                for value in (runner_kind, runner_mode, script_path, script_sha256)
            ):
                raise ReconcileError(
                    "invalid_runner_contract",
                    "runner contract is not allowed",
                )
            resolved_script = self._validated_runner_script(
                step_key=step.step_key,
                runner_kind=runner_kind,
                runner_mode=runner_mode,
                script_path=Path(script_path),
            )

        try:
            submission = SlurmSubmission(
                workflow_id=run.id,
                attempt_id=attempt.id,
                step_key=step.step_key,
                attempt_number=attempt.attempt_number,
                attempt_directory=Path(attempt.working_directory),
                script_path=resolved_script,
                runner_kind=runner_kind,
                runner_mode=runner_mode,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise ReconcileError(
                "invalid_runner_contract",
                "runner contract is not allowed",
            ) from exc

        expected_comment = (
            f"lmatelab:workflow={run.id};attempt={attempt.id}"
            if legacy
            else submission.comment
        )
        if (
            metadata.get("job_name") != submission.job_name
            or metadata.get("comment") != expected_comment
            or (
                not legacy
                and metadata.get("script_sha256") != submission.script_sha256
            )
        ):
            raise ReconcileError(
                "invalid_runner_contract",
                "runner contract is not allowed",
            )
        execution_scope_v1_sha256 = None
        if _EXECUTION_SCOPE_METADATA_KEY in metadata:
            execution_scope_v1_sha256 = metadata[_EXECUTION_SCOPE_METADATA_KEY]
            if (
                runner_kind != "vasp"
                or not _is_lower_hex(execution_scope_v1_sha256, 64)
            ):
                raise ReconcileError(
                    "invalid_runner_contract",
                    "runner contract is not allowed",
                )
        return _AttemptRunnerContract(
            submission=submission,
            expected_comment=expected_comment,
            legacy=legacy,
            execution_scope_v1_sha256=execution_scope_v1_sha256,
        )

    @staticmethod
    def _workload_scheduler_status(runner_kind: str, scheduler_status: str) -> str:
        if runner_kind == "vasp" and scheduler_status == "succeeded":
            return "awaiting_acceptance"
        return scheduler_status

    @staticmethod
    def _scheduler_identity_matches(
        observation: SlurmJobObservation,
        *,
        job_id: str,
        job_name: str,
        working_directory: str,
        comment: str,
        user_name: str | None = None,
    ) -> bool:
        return (
            not observation.stale
            and observation.job_id == job_id
            and observation.job_name == job_name
            and observation.working_directory == working_directory
            and observation.comment == comment
            and (user_name is None or observation.user_name == user_name)
        )

    @staticmethod
    def _active_attempt_exists(session: Session, workflow_id: str) -> bool:
        return bool(
            session.scalar(
                select(func.count())
                .select_from(WorkflowAttempt)
                .join(WorkflowStep, WorkflowStep.id == WorkflowAttempt.step_id)
                .where(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowAttempt.status.in_(_ACTIVE_ATTEMPT_STATUSES),
                )
            )
        )

    def _raise_claim_rejected(
        self,
        session: Session,
        *,
        workflow_id: str,
        step_key: str,
        claimable_run_statuses: frozenset[str],
    ) -> None:
        if self._active_attempt_exists(session, workflow_id):
            raise ReconcileError(
                "workflow_has_active_attempt",
                "workflow already has an active attempt",
            )
        run_status = session.scalar(
            select(WorkflowRun.status).where(WorkflowRun.id == workflow_id)
        )
        if run_status not in claimable_run_statuses:
            raise ReconcileError(
                "workflow_not_claimable",
                "workflow cannot be claimed for submission",
            )
        step_status = session.scalar(
            select(WorkflowStep.status).where(
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.step_key == step_key,
            )
        )
        if step_status != "waiting":
            raise ReconcileError(
                "workflow_step_not_claimable",
                "workflow step cannot be claimed for submission",
            )
        raise ReconcileError(
            "workflow_not_claimable",
            "workflow cannot be claimed for submission",
        )

    def request_retry(
        self,
        session: Session,
        workflow_id: str,
        *,
        owner_id: int,
        step_key: str,
    ) -> None:
        session.rollback()
        run = session.get(WorkflowRun, workflow_id)
        if run is None or run.owner_id != owner_id:
            raise ReconcileError("workflow_not_found", "workflow was not found")
        step = session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.step_key == step_key,
            )
        )
        if step is None:
            raise ReconcileError(
                "workflow_step_invalid",
                "workflow step is outside the fixed workflow",
            )
        active_step = WorkflowStep.__table__.alias("retry_active_step")
        active_attempt_exists = (
            select(WorkflowAttempt.id)
            .select_from(
                WorkflowAttempt.__table__.join(
                    active_step,
                    active_step.c.id == WorkflowAttempt.step_id,
                )
            )
            .where(
                active_step.c.workflow_id == workflow_id,
                WorkflowAttempt.status.in_(_RETRY_BLOCKING_ATTEMPT_STATUSES),
            )
            .exists()
        )
        if session.scalar(select(active_attempt_exists)):
            raise ReconcileError(
                "workflow_has_active_attempt",
                "workflow already has an active attempt",
            )
        latest = session.scalar(
            select(WorkflowAttempt)
            .where(WorkflowAttempt.step_id == step.id)
            .order_by(
                WorkflowAttempt.attempt_number.desc(),
                WorkflowAttempt.id.desc(),
            )
        )
        if latest is None or latest.status not in RETRYABLE_ATTEMPT_STATUSES:
            raise ReconcileError(
                "step_not_retryable",
                "workflow step cannot be retried",
            )
        if step.status != latest.status:
            raise ReconcileError(
                "workflow_ledger_invalid",
                "workflow retry ledger is invalid",
            )

        downstream_attempt_exists = None
        if step_key in {"relax", "scf"}:
            downstream_step = WorkflowStep.__table__.alias(
                "retry_downstream_step"
            )
            downstream_attempt_exists = (
                select(WorkflowAttempt.id)
                .select_from(
                    WorkflowAttempt.__table__.join(
                        downstream_step,
                        downstream_step.c.id == WorkflowAttempt.step_id,
                    )
                )
                .where(
                    downstream_step.c.workflow_id == workflow_id,
                    downstream_step.c.position > step.position,
                )
                .exists()
            )
            if session.scalar(select(downstream_attempt_exists)):
                raise ReconcileError(
                    "step_has_downstream_attempts",
                    "upstream workflow step already has downstream attempts",
                )

        retry_conditions = [
            WorkflowStep.id == step.id,
            WorkflowStep.workflow_id == workflow_id,
            WorkflowStep.status == latest.status,
            ~active_attempt_exists,
        ]
        if downstream_attempt_exists is not None:
            retry_conditions.append(~downstream_attempt_exists)
        retry_requested = session.execute(
            update(WorkflowStep)
            .where(*retry_conditions)
            .values(status="waiting")
            .execution_options(synchronize_session=False)
        )
        if retry_requested.rowcount != 1:
            session.rollback()
            raise ReconcileError(
                "retry_conflict",
                "workflow retry conflicted with another transition",
            )
        if run.status == "cancelled":
            run.status = "failed"
        append_workflow_event(
            session,
            workflow_id=workflow_id,
            event_type="workflow_step_retry_requested",
            payload={"attempt_id": latest.id, "step_key": step_key},
        )
        session.commit()

    def claim_attempt(
        self,
        session: Session,
        workflow_id: str,
        *,
        step_key: str,
        runner_kind: str,
        runner_mode: str,
        script_path: Path,
        claimable_run_statuses: frozenset[str],
        claim_event_type: str | None = None,
    ) -> AttemptClaim:
        resolved_script = self._validated_runner_script(
            step_key=step_key,
            runner_kind=runner_kind,
            runner_mode=runner_mode,
            script_path=script_path,
        )
        if (
            not isinstance(claimable_run_statuses, frozenset)
            or not claimable_run_statuses
            or any(not isinstance(status, str) or not status for status in claimable_run_statuses)
        ):
            raise ReconcileError(
                "invalid_claim_contract",
                "claimable run statuses are invalid",
            )
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")

        session.rollback()
        try:
            active_step = WorkflowStep.__table__.alias("active_step")
            active_attempt_exists = (
                select(WorkflowAttempt.id)
                .select_from(
                    WorkflowAttempt.__table__.join(
                        active_step,
                        active_step.c.id == WorkflowAttempt.step_id,
                    )
                )
                .where(
                    active_step.c.workflow_id == workflow_id,
                    WorkflowAttempt.status.in_(_ACTIVE_ATTEMPT_STATUSES),
                )
                .exists()
            )
            claimable_run_exists = (
                select(WorkflowRun.id)
                .where(
                    WorkflowRun.id == workflow_id,
                    WorkflowRun.status.in_(claimable_run_statuses),
                )
                .exists()
            )
            step_claimed = session.execute(
                update(WorkflowStep)
                .where(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowStep.step_key == step_key,
                    WorkflowStep.status == "waiting",
                    claimable_run_exists,
                    ~active_attempt_exists,
                )
                .values(status="preparing", updated_at=now)
                .execution_options(synchronize_session=False)
            )
            if step_claimed.rowcount != 1:
                session.rollback()
                self._raise_claim_rejected(
                    session,
                    workflow_id=workflow_id,
                    step_key=step_key,
                    claimable_run_statuses=claimable_run_statuses,
                )
            step = session.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowStep.step_key == step_key,
                    WorkflowStep.status == "preparing",
                )
            )
            if step is None:
                raise RuntimeError("claimed workflow step is unavailable")
            run = session.get(WorkflowRun, workflow_id)
            if run is None:
                raise ReconcileError(
                    "workflow_not_claimable",
                    "workflow cannot be claimed for submission",
                )
            execution_scope_v1_sha256 = (
                _execution_scope_v1_sha256(run) if runner_kind == "vasp" else None
            )

            current_attempt = session.scalar(
                select(func.max(WorkflowAttempt.attempt_number)).where(
                    WorkflowAttempt.step_id == step.id
                )
            )
            attempt_number = int(current_attempt or 0) + 1
            attempt_id = str(uuid.uuid4())
            attempt_directory = (
                self._unpublished_vasp_attempt_directory(workflow_id, attempt_id)
                if runner_kind == "vasp"
                else self.slurm.prepare_attempt_directory(workflow_id, attempt_id)
            )
            submission = SlurmSubmission(
                workflow_id=workflow_id,
                attempt_id=attempt_id,
                step_key=step.step_key,
                attempt_number=attempt_number,
                attempt_directory=attempt_directory,
                script_path=resolved_script,
                runner_kind=runner_kind,
                runner_mode=runner_mode,
            )
            attempt_metadata = {
                "comment": submission.comment,
                "job_name": submission.job_name,
                "runner_kind": runner_kind,
                "runner_mode": runner_mode,
                "script_path": str(resolved_script),
                "script_sha256": submission.script_sha256,
            }
            if execution_scope_v1_sha256 is not None:
                attempt_metadata[_EXECUTION_SCOPE_METADATA_KEY] = (
                    execution_scope_v1_sha256
                )
            session.add(
                WorkflowAttempt(
                    id=attempt_id,
                    step_id=step.id,
                    attempt_number=attempt_number,
                    status="preparing",
                    working_directory=str(attempt_directory),
                    metadata_json=attempt_metadata,
                )
            )
            if claim_event_type is not None:
                append_workflow_event(
                    session,
                    workflow_id=workflow_id,
                    event_type=claim_event_type,
                    payload={
                        "attempt_id": attempt_id,
                        "step_key": step.step_key,
                    },
                )
            session.commit()
        except ReconcileError:
            raise
        except Exception:
            session.rollback()
            raise

        return AttemptClaim(
            workflow_id=workflow_id,
            step_id=step.id,
            attempt_id=attempt_id,
            submission=submission,
            status="preparing",
            execution_scope_v1_sha256=execution_scope_v1_sha256,
        )

    def promote_claim(
        self,
        session: Session,
        claim: AttemptClaim,
        *,
        claimable_run_statuses: frozenset[str],
        event_type: str | None = None,
    ) -> AttemptClaim:
        now = self._clock()
        session.rollback()
        session.expire_all()
        if (
            claim.submission.runner_kind == "vasp"
            and claim.execution_scope_v1_sha256 is None
        ):
            raise ReconcileError(
                "invalid_execution_scope",
                "VASP claim is missing its bound execution scope",
            )
        run_conditions = [
            WorkflowRun.id == claim.workflow_id,
            WorkflowRun.status.in_(claimable_run_statuses),
        ]
        if claim.execution_scope_v1_sha256 is not None:
            current_run = session.get(WorkflowRun, claim.workflow_id)
            if not _execution_scope_matches(
                current_run,
                claim.execution_scope_v1_sha256,
            ):
                session.rollback()
                raise ReconcileError(
                    "workflow_scope_changed",
                    "workflow execution scope changed after claim",
                )
            run_conditions.extend(
                (
                    WorkflowRun.template_version == current_run.template_version,
                    WorkflowRun.material == current_run.material,
                    WorkflowRun.source_kind == current_run.source_kind,
                    WorkflowRun.input_sha256 == current_run.input_sha256,
                    WorkflowRun.release_commit == current_run.release_commit,
                    WorkflowRun.metadata_json == current_run.metadata_json,
                )
            )
        attempt = session.execute(
            update(WorkflowAttempt)
            .where(
                WorkflowAttempt.id == claim.attempt_id,
                WorkflowAttempt.status == "preparing",
                WorkflowAttempt.slurm_job_id.is_(None),
            )
            .values(status="submitting", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        step = session.execute(
            update(WorkflowStep)
            .where(
                WorkflowStep.id == claim.step_id,
                WorkflowStep.status == "preparing",
            )
            .values(status="submitting", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        run = session.execute(
            update(WorkflowRun)
            .where(*run_conditions)
            .values(status="submitting", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if (attempt.rowcount, step.rowcount, run.rowcount) != (1, 1, 1):
            session.rollback()
            session.expire_all()
            if claim.execution_scope_v1_sha256 is not None:
                current_run = session.get(WorkflowRun, claim.workflow_id)
                if not _execution_scope_matches(
                    current_run,
                    claim.execution_scope_v1_sha256,
                ):
                    raise ReconcileError(
                        "workflow_scope_changed",
                        "workflow execution scope changed after claim",
                    )
            raise ReconcileError(
                "workflow_not_claimable",
                "workflow cannot be claimed for submission",
            )
        if event_type is not None:
            append_workflow_event(
                session,
                workflow_id=claim.workflow_id,
                event_type=event_type,
                payload={
                    "attempt_id": claim.attempt_id,
                    "step_key": claim.submission.step_key,
                },
            )
        session.commit()
        return AttemptClaim(
            workflow_id=claim.workflow_id,
            step_id=claim.step_id,
            attempt_id=claim.attempt_id,
            submission=claim.submission,
            status="submitting",
            execution_scope_v1_sha256=claim.execution_scope_v1_sha256,
        )

    def load_preparing_claim(
        self,
        session: Session,
        attempt_id: str,
    ) -> AttemptClaim:
        session.rollback()
        attempt = session.get(WorkflowAttempt, attempt_id)
        if (
            attempt is None
            or attempt.status != "preparing"
            or attempt.slurm_job_id is not None
        ):
            raise ReconcileError(
                "attempt_not_preparing",
                "attempt is not recoverable from preparation",
            )
        step = session.get(WorkflowStep, attempt.step_id)
        run = session.get(WorkflowRun, step.workflow_id) if step is not None else None
        if step is None or run is None or step.status != "preparing":
            raise ReconcileError(
                "attempt_not_preparing",
                "attempt is not recoverable from preparation",
            )
        try:
            metadata = json.loads(attempt.metadata_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReconcileError(
                "attempt_not_preparing",
                "attempt is not recoverable from preparation",
            ) from exc
        if not isinstance(metadata, dict):
            raise ReconcileError(
                "attempt_not_preparing",
                "attempt is not recoverable from preparation",
            )
        try:
            contract = self._runner_contract_from_metadata(
                run=run,
                step=step,
                attempt=attempt,
                metadata=metadata,
            )
        except ReconcileError as exc:
            raise ReconcileError(
                "attempt_not_preparing",
                "attempt is not recoverable from preparation",
            ) from exc
        if (
            contract.submission.runner_kind == "vasp"
            and contract.execution_scope_v1_sha256 is None
        ):
            raise ReconcileError(
                "attempt_not_preparing",
                "attempt is not recoverable from preparation",
            )
        return AttemptClaim(
            workflow_id=run.id,
            step_id=step.id,
            attempt_id=attempt.id,
            submission=contract.submission,
            status="preparing",
            execution_scope_v1_sha256=contract.execution_scope_v1_sha256,
        )

    def claim_next_attempt(
        self,
        session: Session,
        workflow_id: str,
        probe_mode: str,
    ) -> AttemptClaim:
        if probe_mode not in PROBE_MODES:
            raise ReconcileError("invalid_probe_mode", "probe mode is not allowed")
        try:
            claim = self.claim_attempt(
                session,
                workflow_id,
                step_key="relax",
                runner_kind="probe",
                runner_mode=probe_mode,
                script_path=self.probe_script,
                claimable_run_statuses=frozenset({"validated"}),
            )
        except ReconcileError as exc:
            if exc.code != "workflow_has_active_attempt":
                raise
            raise ReconcileError(
                "workflow_not_claimable",
                "workflow cannot be claimed for submission",
            ) from exc
        return self.promote_claim(
            session,
            claim,
            claimable_run_statuses=frozenset({"validated"}),
        )

    def _record_submission_failed(
        self,
        session: Session,
        claim: AttemptClaim,
        *,
        reason_code: str,
    ) -> None:
        now = self._clock()
        attempt = session.execute(
            update(WorkflowAttempt)
            .where(
                WorkflowAttempt.id == claim.attempt_id,
                WorkflowAttempt.status == "submitting",
                WorkflowAttempt.slurm_job_id.is_(None),
            )
            .values(status="submission_failed", finished_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        step = session.execute(
            update(WorkflowStep)
            .where(
                WorkflowStep.id == claim.step_id,
                WorkflowStep.status == "submitting",
            )
            .values(status="failed", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        run = session.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == claim.workflow_id,
                WorkflowRun.status == "submitting",
            )
            .values(status="failed", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if (attempt.rowcount, step.rowcount, run.rowcount) != (1, 1, 1):
            session.rollback()
            raise RuntimeError("submission failure transition was lost")
        append_workflow_event(
            session,
            workflow_id=claim.workflow_id,
            event_type="submission_failed",
            payload={
                "attempt_id": claim.attempt_id,
                "reason_code": reason_code,
                "step_key": claim.submission.step_key,
            },
        )
        session.commit()

    def _record_submission_accepted(
        self,
        session: Session,
        claim: AttemptClaim,
        job_id: str,
        *,
        event_type: str = "submission_accepted",
    ) -> SubmissionOutcome:
        now = self._clock()
        attempt = session.execute(
            update(WorkflowAttempt)
            .where(
                WorkflowAttempt.id == claim.attempt_id,
                WorkflowAttempt.status == "submitting",
                WorkflowAttempt.slurm_job_id.is_(None),
            )
            .values(status="queued", slurm_job_id=job_id, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        step = session.execute(
            update(WorkflowStep)
            .where(
                WorkflowStep.id == claim.step_id,
                WorkflowStep.status == "submitting",
            )
            .values(status="queued", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        run = session.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == claim.workflow_id,
                WorkflowRun.status == "submitting",
            )
            .values(status="queued", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if (attempt.rowcount, step.rowcount, run.rowcount) != (1, 1, 1):
            session.rollback()
            raise RuntimeError("submission acceptance transition was lost")
        append_workflow_event(
            session,
            workflow_id=claim.workflow_id,
            event_type=event_type,
            payload={
                "attempt_id": claim.attempt_id,
                "job_id": job_id,
                "step_key": claim.submission.step_key,
            },
        )
        session.commit()
        return SubmissionOutcome(
            workflow_id=claim.workflow_id,
            attempt_id=claim.attempt_id,
            job_id=job_id,
            status="queued",
        )

    def _record_submission_uncertain(
        self,
        session: Session,
        claim: AttemptClaim,
        *,
        reason_code: str,
    ) -> None:
        receipt = claim.submission.attempt_directory / "job-id.receipt"
        receipt_sha256 = None
        try:
            receipt_sha256 = hashlib.sha256(receipt.read_bytes()).hexdigest()
        except OSError:
            pass
        append_workflow_event(
            session,
            workflow_id=claim.workflow_id,
            event_type="submission_uncertain",
            payload={
                "attempt_id": claim.attempt_id,
                "reason_code": reason_code,
                "receipt_sha256": receipt_sha256,
                "step_key": claim.submission.step_key,
            },
        )
        session.commit()

    def _submit_promoted_claim(
        self,
        session: Session,
        claim: AttemptClaim,
    ) -> SubmissionOutcome:
        if claim.status != "submitting":
            raise ReconcileError(
                "attempt_not_submitting",
                "attempt is not ready for scheduler submission",
            )
        try:
            job_id = self.slurm.submit(claim.submission)
        except (SlurmError, ValueError) as exc:
            self._record_submission_failed(
                session,
                claim,
                reason_code="scheduler_rejected",
            )
            raise ReconcileError("submission_failed", "scheduler rejected submission") from exc

        try:
            self.slurm.write_job_receipt(claim.workflow_id, claim.attempt_id, job_id)
            return self._record_submission_accepted(session, claim, job_id)
        except Exception as exc:
            session.rollback()
            try:
                self._record_submission_uncertain(
                    session,
                    claim,
                    reason_code="submission_finalize_failed",
                )
            except Exception:
                session.rollback()
            raise ReconcileError(
                "submission_uncertain",
                "scheduler accepted submission but finalization is uncertain",
            ) from exc

    def submit_claim(
        self,
        session: Session,
        claim: AttemptClaim,
        *,
        claimable_run_statuses: frozenset[str],
    ) -> SubmissionOutcome:
        promoted = self.promote_claim(
            session,
            claim,
            claimable_run_statuses=claimable_run_statuses,
            event_type="submission_started",
        )
        return self._submit_promoted_claim(session, promoted)

    def submit_probe(
        self,
        session: Session,
        workflow_id: str,
        probe_mode: str,
    ) -> SubmissionOutcome:
        claim = self.claim_next_attempt(session, workflow_id, probe_mode)
        return self._submit_promoted_claim(session, claim)

    def recover_submission(
        self,
        session: Session,
        attempt_id: str,
    ) -> SubmissionOutcome:
        session.rollback()
        attempt = session.get(WorkflowAttempt, attempt_id)
        if attempt is None or attempt.status != "submitting" or attempt.slurm_job_id is not None:
            raise ReconcileError(
                "submission_not_recoverable",
                "submission cannot be recovered",
            )
        step = session.get(WorkflowStep, attempt.step_id)
        if step is None:
            raise ReconcileError("submission_not_recoverable", "submission cannot be recovered")
        run = session.get(WorkflowRun, step.workflow_id)
        if run is None or run.status != "submitting" or step.status != "submitting":
            raise ReconcileError("submission_not_recoverable", "submission cannot be recovered")

        try:
            metadata = json.loads(attempt.metadata_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReconcileError(
                "submission_not_recoverable",
                "submission cannot be recovered",
            ) from exc
        if not isinstance(metadata, dict):
            raise ReconcileError("submission_not_recoverable", "submission cannot be recovered")

        try:
            contract = self._runner_contract_from_metadata(
                run=run,
                step=step,
                attempt=attempt,
                metadata=metadata,
            )
        except ReconcileError as exc:
            raise ReconcileError(
                "submission_not_recoverable",
                "submission cannot be recovered",
            ) from exc

        claim = AttemptClaim(
            workflow_id=run.id,
            step_id=step.id,
            attempt_id=attempt.id,
            submission=contract.submission,
            status="submitting",
        )
        try:
            job_id = self.slurm.read_job_receipt(run.id, attempt.id)
        except ValueError as exc:
            self._record_submission_failed(
                session,
                claim,
                reason_code="submission_receipt_missing",
            )
            raise ReconcileError(
                "submission_recovery_failed",
                "submission cannot be recovered without a job receipt",
            ) from exc
        observation = self.slurm.observe(job_id)
        expected_directory = str(
            self.slurm.prepare_attempt_directory(run.id, attempt.id).resolve()
        )
        if not self._scheduler_identity_matches(
            observation,
            job_id=job_id,
            job_name=contract.submission.job_name,
            working_directory=expected_directory,
            comment=contract.expected_comment,
        ):
            raise ReconcileError(
                "submission_recovery_unverified",
                "scheduler ownership evidence did not match the submission",
            )

        return self._record_submission_accepted(
            session,
            claim,
            job_id,
            event_type="submission_recovered",
        )

    @staticmethod
    def _observation_evidence(observation: SlurmJobObservation) -> dict[str, object]:
        return {
            "error_code": observation.error_code,
            "exit_code": observation.exit_code,
            "job_id": observation.job_id,
            "node_list": observation.node_list,
            "observed_at": observation.observed_at.isoformat(),
            "payload_sha256": observation.payload_sha256,
            "raw_state": observation.raw_state,
            "reason": observation.reason,
            "source": observation.source,
            "stale": observation.stale,
            "state": observation.state,
            "started_at": (
                observation.started_at.isoformat()
                if observation.started_at is not None
                else None
            ),
            "finished_at": (
                observation.finished_at.isoformat()
                if observation.finished_at is not None
                else None
            ),
            "user_name": observation.user_name,
        }

    @staticmethod
    def _observation_signature(evidence: dict[str, object]) -> tuple[object, ...]:
        return tuple(
            evidence.get(key)
            for key in (
                "error_code",
                "exit_code",
                "raw_state",
                "reason",
                "source",
                "stale",
                "stale_since",
                "state",
            )
        )

    @staticmethod
    def _decoded_attempt_metadata(attempt: WorkflowAttempt) -> dict[str, object]:
        try:
            metadata = json.loads(attempt.metadata_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReconcileError(
                "cancellation_ownership_mismatch",
                "attempt ownership metadata is invalid",
            ) from exc
        if not isinstance(metadata, dict):
            raise ReconcileError(
                "cancellation_ownership_mismatch",
                "attempt ownership metadata is invalid",
            )
        return metadata

    def _persist_cancel_result(
        self,
        session: Session,
        *,
        run: WorkflowRun,
        step: WorkflowStep,
        attempt: WorkflowAttempt,
        before: SlurmJobObservation,
        status: str,
        result: str,
        event_type: str,
        after: SlurmJobObservation | None = None,
    ) -> CancellationOutcome:
        now = self._clock()
        metadata = self._decoded_attempt_metadata(attempt)
        metadata["before_cancel"] = self._observation_evidence(before)
        metadata["cancel_result"] = {
            "observed_at": now.isoformat(),
            "result": result,
        }
        if after is not None:
            metadata["cancel_result"]["scheduler"] = self._observation_evidence(after)
        attempt.metadata_json = metadata
        attempt.status = status
        attempt.updated_at = now
        step.status = status
        step.updated_at = now
        if status != "awaiting_acceptance":
            run.status = status
        run.updated_at = now
        if status in {"succeeded", "failed", "cancelled"} or (
            after is not None and after.state in {"succeeded", "failed", "cancelled"}
        ):
            attempt.finished_at = (after.finished_at if after is not None else None) or now
        append_workflow_event(
            session,
            workflow_id=run.id,
            event_type=event_type,
            payload={
                "attempt_id": attempt.id,
                "job_id": attempt.slurm_job_id,
                "result": result,
                "status": status,
            },
        )
        session.commit()
        return CancellationOutcome(
            workflow_id=run.id,
            attempt_id=attempt.id,
            job_id=attempt.slurm_job_id,
            status=status,
            result=result,
        )

    def cancel_attempt(
        self,
        session: Session,
        workflow_id: str,
        attempt_id: str,
    ) -> CancellationOutcome:
        if not self.slurm_user:
            raise ReconcileError(
                "cancellation_not_configured",
                "scheduler account is not configured",
            )
        now = self._clock()
        session.rollback()
        attempt = session.get(WorkflowAttempt, attempt_id)
        if attempt is None:
            raise ReconcileError("attempt_not_found", "attempt was not found")
        step = session.get(WorkflowStep, attempt.step_id)
        run = session.get(WorkflowRun, step.workflow_id) if step is not None else None
        if step is None or run is None or run.id != workflow_id:
            raise ReconcileError("attempt_not_found", "attempt was not found")
        if attempt.status not in {"queued", "running"} or not attempt.slurm_job_id:
            raise ReconcileError("job_not_active", "attempt does not have an active job")

        metadata = self._decoded_attempt_metadata(attempt)
        try:
            contract = self._runner_contract_from_metadata(
                run=run,
                step=step,
                attempt=attempt,
                metadata=metadata,
            )
        except ReconcileError as exc:
            raise ReconcileError(
                "cancellation_ownership_mismatch",
                "attempt ownership metadata is invalid",
            ) from exc

        lock = session.execute(
            update(WorkflowAttempt)
            .where(
                WorkflowAttempt.id == attempt.id,
                WorkflowAttempt.slurm_job_id == attempt.slurm_job_id,
                WorkflowAttempt.status.in_(("queued", "running")),
            )
            .values(updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if lock.rowcount != 1:
            session.rollback()
            raise ReconcileError("job_not_active", "attempt does not have an active job")

        try:
            before = self.slurm.inspect_job(attempt.slurm_job_id)
        except (SlurmError, ValueError) as exc:
            session.rollback()
            raise ReconcileError(
                "scheduler_unavailable",
                "scheduler ownership snapshot is unavailable",
            ) from exc

        expected_directory = str(
            self.slurm.prepare_attempt_directory(run.id, attempt.id).resolve()
        )
        ownership_matches = self._scheduler_identity_matches(
            before,
            job_id=attempt.slurm_job_id,
            job_name=contract.submission.job_name,
            working_directory=expected_directory,
            comment=contract.expected_comment,
            user_name=self.slurm_user,
        )
        if not ownership_matches:
            session.rollback()
            raise ReconcileError(
                "cancellation_ownership_mismatch",
                "scheduler ownership evidence did not match the attempt",
            )
        if before.state not in {"queued", "running"}:
            session.rollback()
            raise ReconcileError("job_not_active", "scheduler job is not active")

        try:
            self.slurm.cancel(attempt.slurm_job_id)
        except SlurmError as cancel_error:
            try:
                after = self.slurm.observe(attempt.slurm_job_id)
            except (SlurmError, ValueError):
                after = None
            if after is not None and after.state in {"succeeded", "failed", "cancelled"}:
                if not self._scheduler_identity_matches(
                    after,
                    job_id=attempt.slurm_job_id,
                    job_name=contract.submission.job_name,
                    working_directory=expected_directory,
                    comment=contract.expected_comment,
                    user_name=self.slurm_user,
                ):
                    session.rollback()
                    raise ReconcileError(
                        "cancellation_ownership_mismatch",
                        "scheduler ownership evidence did not match the attempt",
                    )
                return self._persist_cancel_result(
                    session,
                    run=run,
                    step=step,
                    attempt=attempt,
                    before=before,
                    after=after,
                    status=self._workload_scheduler_status(
                        contract.submission.runner_kind,
                        after.state,
                    ),
                    result="raced_terminal",
                    event_type="cancellation_raced_terminal",
                )
            self._persist_cancel_result(
                session,
                run=run,
                step=step,
                attempt=attempt,
                before=before,
                after=after,
                status=attempt.status,
                result="failed",
                event_type="cancellation_failed",
            )
            raise ReconcileError(
                "cancellation_failed",
                "scheduler did not accept cancellation",
            ) from cancel_error

        return self._persist_cancel_result(
            session,
            run=run,
            step=step,
            attempt=attempt,
            before=before,
            status="cancelling",
            result="requested",
            event_type="cancellation_requested",
        )

    def reconcile_attempt(
        self,
        session: Session,
        attempt_id: str,
    ) -> ReconciliationOutcome:
        session.rollback()
        attempt = session.get(WorkflowAttempt, attempt_id)
        if attempt is None or not attempt.slurm_job_id:
            raise ReconcileError(
                "attempt_not_reconcilable",
                "attempt does not have a scheduler job",
            )
        step = session.get(WorkflowStep, attempt.step_id)
        run = session.get(WorkflowRun, step.workflow_id) if step is not None else None
        if step is None or run is None:
            raise ReconcileError(
                "attempt_not_reconcilable",
                "attempt does not have a workflow ledger",
            )

        expected_status = attempt.status
        expected_metadata_json = attempt.metadata_json
        metadata = self._decoded_attempt_metadata(attempt)
        try:
            contract = self._runner_contract_from_metadata(
                run=run,
                step=step,
                attempt=attempt,
                metadata=metadata,
            )
        except ReconcileError as exc:
            raise ReconcileError(
                "attempt_not_reconcilable",
                "attempt runner contract is invalid",
            ) from exc

        try:
            observation = self.slurm.observe(attempt.slurm_job_id)
        except (SlurmError, ValueError) as exc:
            raise ReconcileError(
                "scheduler_unavailable",
                "scheduler observation is unavailable",
            ) from exc

        if not observation.stale:
            expected_directory = str(
                self.slurm.prepare_attempt_directory(run.id, attempt.id).resolve()
            )
            identity_matches = self._scheduler_identity_matches(
                observation,
                job_id=attempt.slurm_job_id,
                job_name=contract.submission.job_name,
                working_directory=expected_directory,
                comment=contract.expected_comment,
                user_name=self.slurm_user,
            )
            if not identity_matches:
                observation = SlurmJobObservation(
                    job_id=observation.job_id,
                    raw_state=observation.raw_state,
                    state="unknown",
                    exit_code=observation.exit_code,
                    reason=observation.reason,
                    source=observation.source,
                    job_name=None,
                    working_directory=None,
                    comment=None,
                    user_name=None,
                    node_list=observation.node_list,
                    observed_at=observation.observed_at,
                    started_at=observation.started_at,
                    finished_at=observation.finished_at,
                    stale=True,
                    error_code="scheduler_ownership_mismatch",
                    payload_sha256=observation.payload_sha256,
                )

        previous = metadata.get("scheduler_observation")
        evidence = self._observation_evidence(observation)
        if observation.stale:
            previous_stale_since = (
                previous.get("stale_since")
                if isinstance(previous, dict) and previous.get("stale") is True
                else None
            )
            evidence["stale_since"] = (
                previous_stale_since
                if isinstance(previous_stale_since, str)
                else observation.observed_at.isoformat()
            )
        state_changed = (
            not isinstance(previous, dict)
            or self._observation_signature(previous)
            != self._observation_signature(evidence)
        )
        metadata["scheduler_observation"] = evidence
        runner_kind = contract.submission.runner_kind
        status = (
            expected_status
            if observation.stale
            and observation.error_code != "scheduler_ownership_mismatch"
            else self._workload_scheduler_status(runner_kind, observation.state)
        )

        now = self._clock()
        attempt_values = {
            "metadata_json": metadata,
            "status": status,
            "updated_at": now,
        }
        if observation.started_at is not None:
            attempt_values["started_at"] = observation.started_at
        if observation.state in {"succeeded", "failed", "cancelled"}:
            attempt_values["finished_at"] = observation.finished_at or observation.observed_at

        transitioned = session.execute(
            update(WorkflowAttempt)
            .where(
                WorkflowAttempt.id == attempt.id,
                WorkflowAttempt.slurm_job_id == attempt.slurm_job_id,
                WorkflowAttempt.status == expected_status,
                WorkflowAttempt.metadata_json == expected_metadata_json,
            )
            .values(**attempt_values)
            .execution_options(synchronize_session=False)
        )
        if transitioned.rowcount != 1:
            workflow_id = run.id
            session.rollback()
            current = session.get(WorkflowAttempt, attempt_id)
            if current is None or not current.slurm_job_id:
                raise ReconcileError(
                    "attempt_not_reconcilable",
                    "attempt does not have a scheduler job",
                )
            return ReconciliationOutcome(
                workflow_id=workflow_id,
                attempt_id=current.id,
                job_id=current.slurm_job_id,
                raw_state=observation.raw_state,
                status=current.status,
                stale=observation.stale,
            )

        step.status = status
        step.updated_at = now
        if observation.state == "succeeded" and runner_kind == "probe":
            statuses = session.scalars(
                select(WorkflowStep.status).where(WorkflowStep.workflow_id == run.id)
            ).all()
            run.status = "succeeded" if statuses and all(
                status == "succeeded" for status in statuses
            ) else "running"
        elif observation.state != "succeeded":
            run.status = status
        run.updated_at = now

        if state_changed:
            append_workflow_event(
                session,
                workflow_id=run.id,
                event_type="scheduler_state_changed",
                payload={
                    "attempt_id": attempt.id,
                    "error_code": observation.error_code,
                    "job_id": attempt.slurm_job_id,
                    "raw_state": observation.raw_state,
                    "stale": observation.stale,
                    "stale_since": evidence.get("stale_since"),
                    "status": status,
                },
            )
        session.commit()
        return ReconciliationOutcome(
            workflow_id=run.id,
            attempt_id=attempt.id,
            job_id=attempt.slurm_job_id,
            raw_state=observation.raw_state,
            status=status,
            stale=observation.stale,
        )
