from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from models_workflow import (
    WorkflowAttempt,
    WorkflowEvent,
    WorkflowFile,
    WorkflowRun,
    WorkflowStep,
    canonical_json,
)
from services.competition_attempt_inputs import prepare_attempt_inputs
from services.competition_inputs import InputValidationError, load_template, validate_draft_payload
from services.competition_reconcile import (
    AttemptClaim,
    CancellationOutcome,
    CompetitionReconciler,
    ReconcileError,
    RETRYABLE_ATTEMPT_STATUSES,
    SubmissionOutcome,
)
from services.competition_vasp import (
    AcceptanceReport,
    FIXED_STAGE_ORDER,
    accept_vasp_attempt,
)
from services.competition_workflows import append_workflow_event


ACTIVE_ATTEMPT_STATUSES: Final = frozenset(
    {
        "preparing",
        "submitting",
        "queued",
        "running",
        "awaiting_acceptance",
        "cancelling",
        "unknown",
    }
)
_CLAIMABLE_RUN_STATUSES: Final = frozenset(
    {"validated", "queued", "running", "failed"}
)
_FAILED_STEP_STATUSES: Final = frozenset({"failed", "scientific_failed"})
_CANCELLATION_RESULTS: Final = frozenset({"requested", "raced_terminal", "failed"})
_CANCELLATION_EVENT_TYPES: Final = frozenset(
    {
        "cancellation_requested",
        "cancellation_raced_terminal",
        "cancellation_failed",
    }
)
_RECONCILABLE_ATTEMPT_STATUSES: Final = frozenset(
    {"queued", "running", "cancelling", "unknown"}
)


class CoordinatorError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CoordinatorOutcome:
    workflow_id: str
    attempt_id: str
    step_key: str
    status: str


@dataclass(frozen=True)
class CoordinatorTickResult:
    processed: int
    failures: int


def next_eligible_step(steps: Mapping[str, str]) -> str | None:
    if steps["relax"] == "waiting":
        return "relax"
    if steps["relax"] == "succeeded" and steps["scf"] == "waiting":
        return "scf"
    if steps["scf"] == "succeeded" and steps["band"] == "waiting":
        return "band"
    band_terminal = steps["band"] in {
        "succeeded",
        "failed",
        "scientific_failed",
    }
    if (
        steps["scf"] == "succeeded"
        and band_terminal
        and steps["dos"] == "waiting"
    ):
        return "dos"
    return None


class CompetitionCoordinator:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        reconciler: CompetitionReconciler,
        workflow_root: str | Path,
        vasp_script: str | Path,
        prepare_inputs: Callable[..., object] = prepare_attempt_inputs,
        accept_attempt: Callable[..., AcceptanceReport] = accept_vasp_attempt,
        batch_limit: int = 8,
    ) -> None:
        if isinstance(batch_limit, bool) or not 1 <= batch_limit <= 32:
            raise ValueError("batch_limit must be between 1 and 32")
        self._session_factory = session_factory
        self.reconciler = reconciler
        self.workflow_root = Path(workflow_root).resolve()
        self.vasp_script = Path(vasp_script).resolve()
        self._prepare_inputs = prepare_inputs
        self._accept_attempt = accept_attempt
        self.batch_limit = batch_limit

    @staticmethod
    def _step_statuses(session: Session, workflow_id: str) -> dict[str, str]:
        rows = session.execute(
            select(
                WorkflowStep.step_key,
                WorkflowStep.position,
                WorkflowStep.status,
            )
            .where(WorkflowStep.workflow_id == workflow_id)
            .order_by(WorkflowStep.position)
        ).all()
        if (
            tuple(row.step_key for row in rows) != FIXED_STAGE_ORDER
            or tuple(row.position for row in rows) != tuple(range(len(FIXED_STAGE_ORDER)))
        ):
            raise CoordinatorError(
                "workflow_shape_invalid",
                "workflow does not have the fixed stage shape",
            )
        return {row.step_key: row.status for row in rows}

    @staticmethod
    def _active_attempts(session: Session, workflow_id: str) -> list[WorkflowAttempt]:
        return list(
            session.scalars(
                select(WorkflowAttempt)
                .join(WorkflowStep, WorkflowStep.id == WorkflowAttempt.step_id)
                .where(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
                )
                .order_by(WorkflowAttempt.created_at, WorkflowAttempt.id)
            )
        )

    @staticmethod
    def _latest_attempt(session: Session, workflow_id: str) -> WorkflowAttempt | None:
        return session.scalar(
            select(WorkflowAttempt)
            .join(WorkflowStep, WorkflowStep.id == WorkflowAttempt.step_id)
            .where(WorkflowStep.workflow_id == workflow_id)
            .order_by(WorkflowAttempt.created_at.desc(), WorkflowAttempt.id.desc())
        )

    @staticmethod
    def _validate_execution_scope(run: WorkflowRun) -> None:
        try:
            template = load_template(run.template_version)
            metadata = json.loads(run.metadata_json)
            normalized_payload = metadata.get("normalized_payload")
            structure_summary = metadata.get("structure_summary")
            validated = validate_draft_payload(normalized_payload)
        except (
            AttributeError,
            InputValidationError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            raise CoordinatorError(
                "workflow_scope_invalid",
                "workflow is outside the fixed execution scope",
            ) from exc
        if (
            validated["template_version"] != run.template_version
            or validated["source_kind"] != run.source_kind
            or not isinstance(structure_summary, dict)
            or structure_summary.get("formula") != run.material
            or tuple(step.get("key") for step in template.get("steps", ()))
            != FIXED_STAGE_ORDER
        ):
            raise CoordinatorError(
                "workflow_scope_invalid",
                "workflow is outside the fixed execution scope",
            )

    @staticmethod
    def _scope_failure_recorded(session: Session, workflow_id: str) -> bool:
        return session.scalar(
            select(WorkflowEvent.id)
            .where(
                WorkflowEvent.workflow_id == workflow_id,
                WorkflowEvent.event_type == "workflow_scope_invalid",
            )
            .limit(1)
        ) is not None

    def _record_scope_failure(
        self,
        session: Session,
        workflow_id: str,
        *,
        attempt_id: str | None = None,
    ) -> None:
        session.rollback()
        session.expire_all()
        run = session.get(WorkflowRun, workflow_id)
        if run is None:
            raise CoordinatorError(
                "workflow_ledger_invalid",
                "workflow ledger is invalid",
            )
        if run.status in {"cancelling", "cancelled"}:
            return

        if attempt_id is not None:
            attempt = session.get(WorkflowAttempt, attempt_id)
            step = (
                session.get(WorkflowStep, attempt.step_id)
                if attempt is not None
                else None
            )
            if step is None or step.workflow_id != workflow_id:
                raise CoordinatorError(
                    "workflow_ledger_invalid",
                    "workflow attempt ledger is invalid",
                )
            attempt_failed = session.execute(
                update(WorkflowAttempt)
                .where(
                    WorkflowAttempt.id == attempt_id,
                    WorkflowAttempt.status == "preparing",
                    WorkflowAttempt.slurm_job_id.is_(None),
                )
                .values(status="submission_failed")
                .execution_options(synchronize_session=False)
            )
            step_failed = session.execute(
                update(WorkflowStep)
                .where(
                    WorkflowStep.id == step.id,
                    WorkflowStep.status == "preparing",
                )
                .values(status="failed")
                .execution_options(synchronize_session=False)
            )
            if (attempt_failed.rowcount, step_failed.rowcount) != (1, 1):
                session.rollback()
                return

        session.execute(
            update(WorkflowStep)
            .where(
                WorkflowStep.workflow_id == workflow_id,
                WorkflowStep.status == "waiting",
            )
            .values(status="blocked")
            .execution_options(synchronize_session=False)
        )
        original_status = run.status
        run_failed = session.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == workflow_id,
                WorkflowRun.status == original_status,
            )
            .values(status="failed")
            .execution_options(synchronize_session=False)
        )
        if run_failed.rowcount != 1:
            session.rollback()
            return
        if not self._scope_failure_recorded(session, workflow_id):
            append_workflow_event(
                session,
                workflow_id=workflow_id,
                event_type="workflow_scope_invalid",
                payload={"reason_code": "workflow_scope_invalid"},
            )
        session.commit()

    def _revalidate_execution_scope(
        self,
        session: Session,
        workflow_id: str,
        *,
        attempt_id: str | None = None,
    ) -> bool:
        session.rollback()
        session.expire_all()
        run = session.get(WorkflowRun, workflow_id)
        if run is None:
            raise CoordinatorError(
                "workflow_ledger_invalid",
                "workflow ledger is invalid",
            )
        try:
            self._validate_execution_scope(run)
        except CoordinatorError as exc:
            if exc.code != "workflow_scope_invalid":
                raise
            self._record_scope_failure(
                session,
                workflow_id,
                attempt_id=attempt_id,
            )
            return False
        return True

    @staticmethod
    def _has_cancellation_intent(session: Session, workflow_id: str) -> bool:
        latest_retry = session.scalar(
            select(func.max(WorkflowEvent.sequence)).where(
                WorkflowEvent.workflow_id == workflow_id,
                WorkflowEvent.event_type == "workflow_step_retry_requested",
            )
        )
        latest_cancel = session.scalar(
            select(func.max(WorkflowEvent.sequence)).where(
                WorkflowEvent.workflow_id == workflow_id,
                WorkflowEvent.event_type.in_(_CANCELLATION_EVENT_TYPES),
            )
        )
        if latest_retry is not None and (
            latest_cancel is None or latest_retry > latest_cancel
        ):
            return False

        metadata_values = session.scalars(
            select(WorkflowAttempt.metadata_json)
            .join(WorkflowStep, WorkflowStep.id == WorkflowAttempt.step_id)
            .where(WorkflowStep.workflow_id == workflow_id)
        ).all()
        for value in metadata_values:
            try:
                metadata = json.loads(value)
            except (TypeError, json.JSONDecodeError) as exc:
                raise CoordinatorError(
                    "workflow_ledger_invalid",
                    "workflow attempt ledger is invalid",
                ) from exc
            cancel_result = metadata.get("cancel_result")
            if (
                isinstance(cancel_result, dict)
                and cancel_result.get("result") in _CANCELLATION_RESULTS
            ):
                return True
        return False

    @staticmethod
    def _outcome(
        session: Session,
        workflow_id: str,
        attempt: WorkflowAttempt,
    ) -> CoordinatorOutcome:
        step = session.get(WorkflowStep, attempt.step_id)
        if step is None or step.workflow_id != workflow_id:
            raise CoordinatorError(
                "workflow_ledger_invalid",
                "workflow attempt ledger is invalid",
            )
        return CoordinatorOutcome(
            workflow_id=workflow_id,
            attempt_id=attempt.id,
            step_key=step.step_key,
            status=attempt.status,
        )

    @staticmethod
    def _request_identity(workflow_id: str, owner_id: int) -> tuple[str, int]:
        try:
            canonical_workflow_id = str(uuid.UUID(workflow_id))
        except (AttributeError, TypeError, ValueError) as exc:
            raise CoordinatorError(
                "workflow_not_found",
                "workflow was not found",
            ) from exc
        if isinstance(owner_id, bool) or not isinstance(owner_id, int) or owner_id < 1:
            raise CoordinatorError("workflow_not_found", "workflow was not found")
        return canonical_workflow_id, owner_id

    def start(self, workflow_id: str, owner_id: int) -> CoordinatorOutcome:
        workflow_id, owner_id = self._request_identity(workflow_id, owner_id)

        with self._session_factory() as session:
            run = session.get(WorkflowRun, workflow_id)
            if run is None or run.owner_id != owner_id:
                raise CoordinatorError("workflow_not_found", "workflow was not found")
            self._validate_execution_scope(run)
            self._step_statuses(session, workflow_id)
            existing = self._latest_attempt(session, workflow_id)
            if existing is not None:
                return self._outcome(session, workflow_id, existing)
            if run.status != "validated":
                raise CoordinatorError(
                    "workflow_not_startable",
                    "workflow is not ready to start",
                )

        outcome = self._advance(workflow_id, owner_id)
        if outcome is not None:
            return outcome
        with self._session_factory() as session:
            existing = self._latest_attempt(session, workflow_id)
            if existing is not None:
                return self._outcome(session, workflow_id, existing)
        raise CoordinatorError(
            "workflow_not_startable",
            "workflow could not be started",
        )

    def retry(
        self,
        workflow_id: str,
        owner_id: int,
        step_key: str,
    ) -> CoordinatorOutcome:
        workflow_id, owner_id = self._request_identity(workflow_id, owner_id)
        if step_key not in FIXED_STAGE_ORDER:
            raise CoordinatorError(
                "workflow_step_invalid",
                "workflow step is outside the fixed workflow",
            )

        with self._session_factory() as session:
            run = session.get(WorkflowRun, workflow_id)
            if run is None or run.owner_id != owner_id:
                raise CoordinatorError("workflow_not_found", "workflow was not found")
            self._validate_execution_scope(run)
            self._step_statuses(session, workflow_id)
            try:
                self.reconciler.request_retry(
                    session,
                    workflow_id,
                    owner_id=owner_id,
                    step_key=step_key,
                )
            except ReconcileError as exc:
                raise CoordinatorError(exc.code, str(exc)) from exc

        outcome = self._advance(workflow_id, owner_id)
        if outcome is not None:
            return outcome
        raise CoordinatorError(
            "retry_conflict",
            "workflow retry could not claim a new attempt",
        )

    def cancel(self, workflow_id: str, owner_id: int) -> CancellationOutcome:
        workflow_id, owner_id = self._request_identity(workflow_id, owner_id)

        with self._session_factory() as session:
            run = session.get(WorkflowRun, workflow_id)
            if run is None or run.owner_id != owner_id:
                raise CoordinatorError("workflow_not_found", "workflow was not found")
            self._step_statuses(session, workflow_id)
            active = self._active_attempts(session, workflow_id)
            if not active:
                raise CoordinatorError(
                    "workflow_not_cancellable",
                    "workflow does not have an active attempt",
                )
            if len(active) != 1:
                raise CoordinatorError(
                    "multiple_active_attempts",
                    "workflow has multiple active attempts",
                )
            try:
                return self.reconciler.cancel_attempt(
                    session,
                    workflow_id,
                    active[0].id,
                )
            except ReconcileError as exc:
                raise CoordinatorError(exc.code, str(exc)) from exc

    def tick_once(self) -> CoordinatorTickResult:
        with self._session_factory() as session:
            active_workflows = list(
                session.scalars(
                    select(WorkflowStep.workflow_id)
                    .join(
                        WorkflowAttempt,
                        WorkflowAttempt.step_id == WorkflowStep.id,
                    )
                    .where(WorkflowAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES))
                    .distinct()
                    .order_by(WorkflowStep.workflow_id)
                    .limit(self.batch_limit)
                )
            )
            remaining = self.batch_limit - len(active_workflows)
            recoverable_workflows: list[str] = []
            if remaining:
                recoverable_workflows = list(
                    session.scalars(
                        select(WorkflowStep.workflow_id)
                        .join(
                            WorkflowAttempt,
                            WorkflowAttempt.step_id == WorkflowStep.id,
                        )
                        .join(
                            WorkflowRun,
                            WorkflowRun.id == WorkflowStep.workflow_id,
                        )
                        .where(
                            ~WorkflowStep.workflow_id.in_(active_workflows),
                            WorkflowRun.status.in_({"queued", "running", "failed"}),
                        )
                        .distinct()
                        .order_by(WorkflowStep.workflow_id)
                        .limit(remaining)
                    )
                )
        workflow_ids = [*active_workflows, *recoverable_workflows]
        failures = 0
        for workflow_id in workflow_ids:
            try:
                self._tick_workflow(workflow_id)
            except Exception:
                failures += 1
        return CoordinatorTickResult(processed=len(workflow_ids), failures=failures)

    def _tick_workflow(self, workflow_id: str) -> None:
        with self._session_factory() as session:
            active = self._active_attempts(session, workflow_id)
            if len(active) > 1:
                raise CoordinatorError(
                    "multiple_active_attempts",
                    "workflow has multiple active attempts",
                )
            active_id = active[0].id if active else None
            active_status = active[0].status if active else None

        if active_id is not None:
            if active_status == "preparing":
                self._resume_preparing(active_id)
                return
            if active_status == "submitting":
                with self._session_factory() as session:
                    self.reconciler.recover_submission(session, active_id)
                return
            if active_status in _RECONCILABLE_ATTEMPT_STATUSES:
                with self._session_factory() as session:
                    observed = self.reconciler.reconcile_attempt(session, active_id)
                if observed.stale or observed.status == "unknown":
                    return
                if observed.status in ACTIVE_ATTEMPT_STATUSES:
                    if observed.status != "awaiting_acceptance":
                        return
                    active_status = "awaiting_acceptance"
                else:
                    active_status = observed.status
            if active_status == "awaiting_acceptance":
                self._accept_completed_attempt(active_id)

        with self._session_factory() as session:
            run = session.get(WorkflowRun, workflow_id)
            if run is None:
                return
            owner_id = run.owner_id
            if self._active_attempts(session, workflow_id):
                return
            cancelled = self._has_cancellation_intent(session, workflow_id)
        if cancelled:
            self._aggregate_run_status(workflow_id)
            return
        if self._advance(workflow_id, owner_id) is None:
            self._aggregate_run_status(workflow_id)

    def _resume_preparing(self, attempt_id: str) -> CoordinatorOutcome:
        with self._session_factory() as session:
            claim = self.reconciler.load_preparing_claim(session, attempt_id)
            run = session.get(WorkflowRun, claim.workflow_id)
            step = session.get(WorkflowStep, claim.step_id)
            if run is None or step is None:
                raise CoordinatorError(
                    "workflow_ledger_invalid",
                    "workflow attempt ledger is invalid",
                )
            if not self._revalidate_execution_scope(
                session,
                claim.workflow_id,
                attempt_id=claim.attempt_id,
            ):
                session.expire_all()
                return self._outcome(
                    session,
                    claim.workflow_id,
                    session.get(WorkflowAttempt, claim.attempt_id),
                )
            run = session.get(WorkflowRun, claim.workflow_id)
            step = session.get(WorkflowStep, claim.step_id)
            self._prepare_inputs(
                session,
                self.workflow_root,
                owner_id=run.owner_id,
                workflow_id=run.id,
                step_key=step.step_key,
                attempt_id=claim.attempt_id,
                template_version=run.template_version,
                release_commit=run.release_commit,
            )
            if not self._revalidate_execution_scope(
                session,
                claim.workflow_id,
                attempt_id=claim.attempt_id,
            ):
                session.expire_all()
                return self._outcome(
                    session,
                    claim.workflow_id,
                    session.get(WorkflowAttempt, claim.attempt_id),
                )
            submission = self._submit_scope_bound_claim(session, claim)
            if submission is None:
                session.expire_all()
                return self._outcome(
                    session,
                    claim.workflow_id,
                    session.get(WorkflowAttempt, claim.attempt_id),
                )
        return CoordinatorOutcome(
            workflow_id=submission.workflow_id,
            attempt_id=submission.attempt_id,
            step_key=claim.submission.step_key,
            status=submission.status,
        )

    def _submit_scope_bound_claim(
        self,
        session: Session,
        claim: AttemptClaim,
    ) -> SubmissionOutcome | None:
        try:
            return self.reconciler.submit_claim(
                session,
                claim,
                claimable_run_statuses=_CLAIMABLE_RUN_STATUSES,
            )
        except ReconcileError as exc:
            if exc.code != "workflow_scope_changed":
                raise
            self._record_scope_failure(
                session,
                claim.workflow_id,
                attempt_id=claim.attempt_id,
            )
            return None

    @staticmethod
    def _release_blocked_descendants_after_retry(
        session: Session,
        *,
        run: WorkflowRun,
        step: WorkflowStep,
        attempt: WorkflowAttempt,
    ) -> None:
        if (
            attempt.attempt_number <= 1
            or step.step_key not in {"relax", "scf"}
        ):
            return
        descendants = list(
            session.scalars(
                select(WorkflowStep)
                .where(
                    WorkflowStep.workflow_id == run.id,
                    WorkflowStep.position > step.position,
                )
                .order_by(WorkflowStep.position)
            )
        )
        for descendant in descendants:
            has_attempt = session.scalar(
                select(WorkflowAttempt.id)
                .where(WorkflowAttempt.step_id == descendant.id)
                .limit(1)
            )
            if has_attempt is not None:
                raise CoordinatorError(
                    "acceptance_ledger_invalid",
                    "retried upstream step has downstream attempts",
                )
            if descendant.status == "waiting":
                continue
            if descendant.status != "blocked":
                raise CoordinatorError(
                    "acceptance_ledger_invalid",
                    "retried upstream step has invalid downstream state",
                )
            descendant.status = "waiting"
            append_workflow_event(
                session,
                workflow_id=run.id,
                event_type="workflow_step_unblocked",
                payload={
                    "attempt_id": attempt.id,
                    "step_key": descendant.step_key,
                    "unblocked_by": step.step_key,
                },
            )

    def _accept_completed_attempt(self, attempt_id: str) -> bool:
        with self._session_factory() as session:
            session.rollback()
            attempt = session.get(WorkflowAttempt, attempt_id)
            if attempt is None or attempt.status != "awaiting_acceptance":
                return False
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, step.workflow_id) if step is not None else None
            if (
                step is None
                or run is None
                or step.status != "awaiting_acceptance"
                or not attempt.slurm_job_id
                or not attempt.working_directory
            ):
                raise CoordinatorError(
                    "acceptance_ledger_invalid",
                    "attempt cannot be scientifically accepted",
                )
            try:
                metadata = json.loads(attempt.metadata_json)
            except (TypeError, json.JSONDecodeError) as exc:
                raise CoordinatorError(
                    "acceptance_ledger_invalid",
                    "attempt cannot be scientifically accepted",
                ) from exc
            cancel_result = metadata.get("cancel_result")
            if (
                isinstance(cancel_result, dict)
                and cancel_result.get("result") in _CANCELLATION_RESULTS
            ):
                attempt_cancelled = session.execute(
                    update(WorkflowAttempt)
                    .where(
                        WorkflowAttempt.id == attempt.id,
                        WorkflowAttempt.status == "awaiting_acceptance",
                        WorkflowAttempt.slurm_job_id == attempt.slurm_job_id,
                        WorkflowAttempt.metadata_json == attempt.metadata_json,
                    )
                    .values(status="cancelled")
                    .execution_options(synchronize_session=False)
                )
                step_cancelled = session.execute(
                    update(WorkflowStep)
                    .where(
                        WorkflowStep.id == step.id,
                        WorkflowStep.status == "awaiting_acceptance",
                    )
                    .values(status="cancelled")
                    .execution_options(synchronize_session=False)
                )
                run_cancelled = session.execute(
                    update(WorkflowRun)
                    .where(
                        WorkflowRun.id == run.id,
                        WorkflowRun.status == run.status,
                    )
                    .values(status="cancelled")
                    .execution_options(synchronize_session=False)
                )
                if (
                    attempt_cancelled.rowcount,
                    step_cancelled.rowcount,
                    run_cancelled.rowcount,
                ) != (1, 1, 1):
                    session.rollback()
                    return False
                append_workflow_event(
                    session,
                    workflow_id=run.id,
                    event_type="workflow_status_changed",
                    payload={"status": "cancelled"},
                )
                session.commit()
                return False
            observation = metadata.get("scheduler_observation")
            if (
                not isinstance(observation, dict)
                or observation.get("job_id") != attempt.slurm_job_id
                or observation.get("state") != "succeeded"
                or observation.get("raw_state") != "COMPLETED"
                or observation.get("exit_code") != "0:0"
                or observation.get("stale") is not False
                or observation.get("error_code") is not None
            ):
                raise CoordinatorError(
                    "acceptance_scheduler_untrusted",
                    "scheduler evidence is not trusted for acceptance",
                )
            report = self._accept_attempt(
                Path(attempt.working_directory),
                step.step_key,
                scheduler_state=observation["raw_state"],
                scheduler_exit_code=observation["exit_code"],
            )
            if not isinstance(report, AcceptanceReport):
                raise CoordinatorError(
                    "acceptance_report_invalid",
                    "scientific acceptance returned an invalid report",
                )
            report_dict = report.as_dict()
            encoded = canonical_json(report_dict)
            report_sha256 = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            result_status = "succeeded" if report.accepted else "scientific_failed"

            claim = session.execute(
                update(WorkflowAttempt)
                .where(
                    WorkflowAttempt.id == attempt.id,
                    WorkflowAttempt.status == "awaiting_acceptance",
                    WorkflowAttempt.slurm_job_id == attempt.slurm_job_id,
                )
                .values(status=result_status)
                .execution_options(synchronize_session=False)
            )
            step_claim = session.execute(
                update(WorkflowStep)
                .where(
                    WorkflowStep.id == step.id,
                    WorkflowStep.status == "awaiting_acceptance",
                )
                .values(status=result_status)
                .execution_options(synchronize_session=False)
            )
            if (claim.rowcount, step_claim.rowcount) != (1, 1):
                session.rollback()
                return False

            if run.status == "unknown":
                run_recovered = session.execute(
                    update(WorkflowRun)
                    .where(
                        WorkflowRun.id == run.id,
                        WorkflowRun.status == "unknown",
                    )
                    .values(status="running")
                    .execution_options(synchronize_session=False)
                )
                if run_recovered.rowcount != 1:
                    session.rollback()
                    return False
                append_workflow_event(
                    session,
                    workflow_id=run.id,
                    event_type="workflow_status_changed",
                    payload={"status": "running"},
                )

            metadata["scientific_acceptance"] = report_dict
            metadata["scientific_acceptance_sha256"] = report_sha256
            metadata_updated = session.execute(
                update(WorkflowAttempt)
                .where(
                    WorkflowAttempt.id == attempt.id,
                    WorkflowAttempt.status == result_status,
                )
                .values(metadata_json=metadata)
                .execution_options(synchronize_session=False)
            )
            if metadata_updated.rowcount != 1:
                session.rollback()
                return False
            if report.accepted:
                self._release_blocked_descendants_after_retry(
                    session,
                    run=run,
                    step=step,
                    attempt=attempt,
                )
            for artifact in report.artifacts:
                name = artifact["name"]
                relative_path = f"{run.id}/attempts/{attempt.id}/{name}"
                existing = session.scalar(
                    select(WorkflowFile).where(
                        WorkflowFile.workflow_id == run.id,
                        WorkflowFile.relative_path == relative_path,
                    )
                )
                if existing is not None:
                    if (
                        existing.attempt_id != attempt.id
                        or existing.sha256 != artifact["sha256"]
                        or existing.size_bytes != artifact["size_bytes"]
                    ):
                        raise CoordinatorError(
                            "acceptance_output_mismatch",
                            "acceptance output ledger does not match the report",
                        )
                    continue
                session.add(
                    WorkflowFile(
                        id=str(uuid.uuid4()),
                        workflow_id=run.id,
                        attempt_id=attempt.id,
                        owner_id=run.owner_id,
                        relative_path=relative_path,
                        size_bytes=artifact["size_bytes"],
                        sha256=artifact["sha256"],
                        source_kind="attempt_output",
                        metadata_json={
                            "accepted": True,
                            "logical_path": name,
                            "step_key": step.step_key,
                            "output_role": "scientific_acceptance_evidence",
                            "release_commit": run.release_commit,
                            "acceptance_report_sha256": report_sha256,
                        },
                    )
                )
            append_workflow_event(
                session,
                workflow_id=run.id,
                event_type="scientific_acceptance_completed",
                payload={
                    "attempt_id": attempt.id,
                    "accepted": report.accepted,
                    "reason_code": report.reason_code,
                },
            )
            session.commit()
            return True

    def _advance(self, workflow_id: str, owner_id: int) -> CoordinatorOutcome | None:
        with self._session_factory() as session:
            run = session.get(WorkflowRun, workflow_id)
            if run is None or run.owner_id != owner_id:
                return None
            if self._active_attempts(session, workflow_id):
                return None
            if self._has_cancellation_intent(session, workflow_id):
                return None
            if not self._revalidate_execution_scope(session, workflow_id):
                return None
            steps = self._step_statuses(session, workflow_id)
            step_key = next_eligible_step(steps)
            if step_key is None:
                return None
            if run.status not in _CLAIMABLE_RUN_STATUSES:
                return None
            try:
                claim = self.reconciler.claim_attempt(
                    session,
                    workflow_id,
                    step_key=step_key,
                    runner_kind="vasp",
                    runner_mode=step_key,
                    script_path=self.vasp_script,
                    claimable_run_statuses=_CLAIMABLE_RUN_STATUSES,
                    claim_event_type="workflow_step_claimed",
                )
            except ReconcileError as exc:
                if exc.code in {
                    "workflow_has_active_attempt",
                    "workflow_step_not_claimable",
                    "workflow_not_claimable",
                }:
                    return None
                raise
            if not self._revalidate_execution_scope(
                session,
                workflow_id,
                attempt_id=claim.attempt_id,
            ):
                return None
            run = session.get(WorkflowRun, workflow_id)
            self._prepare_inputs(
                session,
                self.workflow_root,
                owner_id=owner_id,
                workflow_id=workflow_id,
                step_key=step_key,
                attempt_id=claim.attempt_id,
                template_version=run.template_version,
                release_commit=run.release_commit,
            )
            if not self._revalidate_execution_scope(
                session,
                workflow_id,
                attempt_id=claim.attempt_id,
            ):
                return None
            submission = self._submit_scope_bound_claim(session, claim)
            if submission is None:
                return None
        return CoordinatorOutcome(
            workflow_id=workflow_id,
            attempt_id=submission.attempt_id,
            step_key=step_key,
            status=submission.status,
        )

    def _aggregate_run_status(self, workflow_id: str) -> str | None:
        with self._session_factory() as session:
            run = session.get(WorkflowRun, workflow_id)
            if run is None or self._active_attempts(session, workflow_id):
                return None
            statuses = self._step_statuses(session, workflow_id)
            blocked_by: tuple[str, str] | None = None
            if statuses["relax"] in _FAILED_STEP_STATUSES:
                blocked_by = ("relax", statuses["relax"])
                targets = ("scf", "band", "dos")
            elif statuses["scf"] in _FAILED_STEP_STATUSES:
                blocked_by = ("scf", statuses["scf"])
                targets = ("band", "dos")
            else:
                targets = ()
            for step_key in targets:
                blocked = session.execute(
                    update(WorkflowStep)
                    .where(
                        WorkflowStep.workflow_id == workflow_id,
                        WorkflowStep.step_key == step_key,
                        WorkflowStep.status == "waiting",
                    )
                    .values(status="blocked")
                    .execution_options(synchronize_session=False)
                )
                if blocked.rowcount:
                    append_workflow_event(
                        session,
                        workflow_id=workflow_id,
                        event_type="workflow_step_blocked",
                        payload={
                            "step_key": step_key,
                            "blocked_by": blocked_by[0],
                            "reason_status": blocked_by[1],
                        },
                    )
            session.flush()
            statuses = self._step_statuses(session, workflow_id)
            cancelled = self._has_cancellation_intent(session, workflow_id)
            if cancelled:
                aggregate = "cancelled"
            elif all(status == "succeeded" for status in statuses.values()):
                aggregate = "succeeded"
            elif any(status == "cancelled" for status in statuses.values()):
                aggregate = "cancelled"
            elif any(status in _FAILED_STEP_STATUSES for status in statuses.values()):
                aggregate = "failed"
            elif any(status == "unknown" for status in statuses.values()):
                aggregate = "unknown"
            else:
                aggregate = run.status

            if aggregate != run.status:
                changed = session.execute(
                    update(WorkflowRun)
                    .where(
                        WorkflowRun.id == workflow_id,
                        WorkflowRun.status == run.status,
                    )
                    .values(status=aggregate)
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    session.rollback()
                    return None
                append_workflow_event(
                    session,
                    workflow_id=workflow_id,
                    event_type="workflow_status_changed",
                    payload={"status": aggregate},
                )
            session.commit()
            return aggregate
