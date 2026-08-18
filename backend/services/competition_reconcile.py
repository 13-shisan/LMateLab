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

from models_workflow import WorkflowAttempt, WorkflowRun, WorkflowStep
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


@dataclass(frozen=True)
class SubmissionOutcome:
    workflow_id: str
    attempt_id: str
    job_id: str
    status: str


@dataclass(frozen=True)
class CancellationOutcome:
    workflow_id: str
    attempt_id: str
    job_id: str
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

    def _runner_contract_from_metadata(
        self,
        *,
        step_key: str,
        metadata: dict[str, object],
    ) -> tuple[str, str, Path]:
        runner_kind = metadata.get("runner_kind")
        runner_mode = metadata.get("runner_mode")
        script_path = metadata.get("script_path")
        if not all(isinstance(value, str) for value in (runner_kind, runner_mode, script_path)):
            raise ReconcileError(
                "invalid_runner_contract",
                "runner contract is not allowed",
            )
        resolved_script = self._validated_runner_script(
            step_key=step_key,
            runner_kind=runner_kind,
            runner_mode=runner_mode,
            script_path=Path(script_path),
        )
        return runner_kind, runner_mode, resolved_script

    @staticmethod
    def _workload_scheduler_status(runner_kind: str, scheduler_status: str) -> str:
        if runner_kind == "vasp" and scheduler_status == "succeeded":
            return "awaiting_acceptance"
        return scheduler_status

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

            current_attempt = session.scalar(
                select(func.max(WorkflowAttempt.attempt_number)).where(
                    WorkflowAttempt.step_id == step.id
                )
            )
            attempt_number = int(current_attempt or 0) + 1
            attempt_id = str(uuid.uuid4())
            attempt_directory = self.slurm.prepare_attempt_directory(
                workflow_id,
                attempt_id,
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
            session.add(
                WorkflowAttempt(
                    id=attempt_id,
                    step_id=step.id,
                    attempt_number=attempt_number,
                    status="preparing",
                    working_directory=str(attempt_directory),
                    metadata_json={
                        "comment": submission.comment,
                        "job_name": submission.job_name,
                        "runner_kind": runner_kind,
                        "runner_mode": runner_mode,
                        "script_path": str(resolved_script),
                    },
                )
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
        )

    def _promote_probe_claim(
        self,
        session: Session,
        claim: AttemptClaim,
    ) -> AttemptClaim:
        now = self._clock()
        session.rollback()
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
            .where(
                WorkflowRun.id == claim.workflow_id,
                WorkflowRun.status == "validated",
            )
            .values(status="submitting", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if (attempt.rowcount, step.rowcount, run.rowcount) != (1, 1, 1):
            session.rollback()
            raise ReconcileError(
                "workflow_not_claimable",
                "workflow cannot be claimed for submission",
            )
        session.commit()
        return AttemptClaim(
            workflow_id=claim.workflow_id,
            step_id=claim.step_id,
            attempt_id=claim.attempt_id,
            submission=claim.submission,
            status="submitting",
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
        return self._promote_probe_claim(session, claim)

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

    def submit_probe(
        self,
        session: Session,
        workflow_id: str,
        probe_mode: str,
    ) -> SubmissionOutcome:
        claim = self.claim_next_attempt(session, workflow_id, probe_mode)
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
            runner_kind, runner_mode, script_path = self._runner_contract_from_metadata(
                step_key=step.step_key,
                metadata=metadata,
            )
        except ReconcileError as exc:
            raise ReconcileError(
                "submission_not_recoverable",
                "submission cannot be recovered",
            ) from exc

        job_id = self.slurm.read_job_receipt(run.id, attempt.id)
        observation = self.slurm.observe(job_id)
        expected_directory = str(
            self.slurm.prepare_attempt_directory(run.id, attempt.id).resolve()
        )
        if (
            observation.stale
            or observation.job_name != metadata.get("job_name")
            or observation.working_directory != expected_directory
            or observation.comment != metadata.get("comment")
        ):
            raise ReconcileError(
                "submission_recovery_unverified",
                "scheduler ownership evidence did not match the submission",
            )

        submission = SlurmSubmission(
            workflow_id=run.id,
            attempt_id=attempt.id,
            step_key=step.step_key,
            attempt_number=attempt.attempt_number,
            attempt_directory=Path(expected_directory),
            script_path=script_path,
            runner_kind=runner_kind,
            runner_mode=runner_mode,
        )
        claim = AttemptClaim(
            workflow_id=run.id,
            step_id=step.id,
            attempt_id=attempt.id,
            submission=submission,
            status="submitting",
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
        expected_comment = f"lmatelab:workflow={run.id};attempt={attempt.id}"
        ownership_matches = (
            not before.stale
            and before.job_id == attempt.slurm_job_id
            and isinstance(before.job_name, str)
            and before.job_name.startswith("lmatelab-")
            and before.working_directory == expected_directory
            and before.comment == expected_comment
            and before.user_name == self.slurm_user
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
                metadata = self._decoded_attempt_metadata(attempt)
                try:
                    runner_kind, _runner_mode, _script_path = (
                        self._runner_contract_from_metadata(
                            step_key=step.step_key,
                            metadata=metadata,
                        )
                    )
                except ReconcileError as exc:
                    raise ReconcileError(
                        "cancellation_ownership_mismatch",
                        "attempt ownership metadata is invalid",
                    ) from exc
                return self._persist_cancel_result(
                    session,
                    run=run,
                    step=step,
                    attempt=attempt,
                    before=before,
                    after=after,
                    status=self._workload_scheduler_status(runner_kind, after.state),
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
            expected_comment = f"lmatelab:workflow={run.id};attempt={attempt.id}"
            identity_matches = (
                observation.job_id == attempt.slurm_job_id
                and isinstance(observation.job_name, str)
                and observation.job_name.startswith("lmatelab-")
                and observation.working_directory == expected_directory
                and observation.comment == expected_comment
                and (
                    self.slurm_user is None
                    or observation.user_name == self.slurm_user
                )
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

        metadata = self._decoded_attempt_metadata(attempt)
        try:
            runner_kind, _runner_mode, _script_path = self._runner_contract_from_metadata(
                step_key=step.step_key,
                metadata=metadata,
            )
        except ReconcileError as exc:
            raise ReconcileError(
                "attempt_not_reconcilable",
                "attempt runner contract is invalid",
            ) from exc
        previous = metadata.get("scheduler_observation")
        evidence = self._observation_evidence(observation)
        state_changed = (
            not isinstance(previous, dict)
            or self._observation_signature(previous)
            != self._observation_signature(evidence)
        )
        metadata["scheduler_observation"] = evidence
        status = self._workload_scheduler_status(runner_kind, observation.state)

        now = self._clock()
        attempt.metadata_json = metadata
        attempt.status = status
        attempt.updated_at = now
        if observation.started_at is not None:
            attempt.started_at = observation.started_at
        if observation.state in {"succeeded", "failed", "cancelled"}:
            attempt.finished_at = observation.finished_at or observation.observed_at

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
