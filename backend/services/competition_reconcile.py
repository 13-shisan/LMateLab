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
    PROBE_MODES,
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CompetitionReconciler:
    def __init__(
        self,
        *,
        slurm: SlurmClient,
        probe_script: Path,
        clock: Callable[[], datetime] = _utc_now,
        slurm_user: str | None = None,
    ) -> None:
        self.slurm = slurm
        self.probe_script = Path(probe_script).resolve()
        self._clock = clock
        self.slurm_user = slurm_user

    def claim_next_attempt(
        self,
        session: Session,
        workflow_id: str,
        probe_mode: str,
    ) -> AttemptClaim:
        if probe_mode not in PROBE_MODES:
            raise ReconcileError("invalid_probe_mode", "probe mode is not allowed")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return an aware datetime")

        session.rollback()
        try:
            claimed = session.execute(
                update(WorkflowRun)
                .where(
                    WorkflowRun.id == workflow_id,
                    WorkflowRun.status == "validated",
                )
                .values(status="submitting", updated_at=now)
                .execution_options(synchronize_session=False)
            )
            if claimed.rowcount != 1:
                session.rollback()
                raise ReconcileError(
                    "workflow_not_claimable",
                    "workflow cannot be claimed for submission",
                )

            step = session.scalar(
                select(WorkflowStep)
                .where(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowStep.status == "waiting",
                )
                .order_by(WorkflowStep.position)
                .limit(1)
            )
            if step is None:
                raise RuntimeError("claimed workflow has no waiting step")
            step_claimed = session.execute(
                update(WorkflowStep)
                .where(
                    WorkflowStep.id == step.id,
                    WorkflowStep.status == "waiting",
                )
                .values(status="submitting", updated_at=now)
                .execution_options(synchronize_session=False)
            )
            if step_claimed.rowcount != 1:
                raise RuntimeError("workflow step claim was lost")

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
                script_path=self.probe_script,
                probe_mode=probe_mode,
            )
            session.add(
                WorkflowAttempt(
                    id=attempt_id,
                    step_id=step.id,
                    attempt_number=attempt_number,
                    status="submitting",
                    working_directory=str(attempt_directory),
                    metadata_json={
                        "comment": submission.comment,
                        "job_name": submission.job_name,
                        "probe_mode": probe_mode,
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
            script_path=self.probe_script,
            probe_mode=metadata.get("probe_mode"),
        )
        claim = AttemptClaim(
            workflow_id=run.id,
            step_id=step.id,
            attempt_id=attempt.id,
            submission=submission,
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
            "user_name": observation.user_name,
        }

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
        run.status = status
        run.updated_at = now
        if status in {"succeeded", "failed", "cancelled"}:
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
                return self._persist_cancel_result(
                    session,
                    run=run,
                    step=step,
                    attempt=attempt,
                    before=before,
                    after=after,
                    status=after.state,
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
