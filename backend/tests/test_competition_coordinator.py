import hashlib
import json
import tempfile
import threading
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from database import Base
from models import User
from models_workflow import (
    WorkflowAttempt,
    WorkflowEvent,
    WorkflowFile,
    WorkflowRun,
    WorkflowStep,
    canonical_json,
)
from services.competition_coordinator import (
    ACTIVE_ATTEMPT_STATUSES,
    CompetitionCoordinator,
    CoordinatorError,
    next_eligible_step,
)
from services.competition_attempt_inputs import prepare_attempt_inputs
from services.competition_reconcile import CompetitionReconciler
from services.competition_slurm import SlurmJobObservation
from services.competition_vasp import AcceptanceReport


FIXED_STEPS = ("relax", "scf", "band", "dos")


class FakeSlurm:
    def __init__(self, root: Path):
        self.root = root
        self.workflow_root = root.resolve()
        self.submitted_steps = []
        self.submissions = {}
        self.receipts = {}
        self.jobs = {}
        self.next_job_id = 71000

    def prepare_attempt_directory(self, workflow_id, attempt_id):
        directory = self.root / workflow_id / "attempts" / attempt_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory.resolve()

    def submit(self, submission):
        job_id = str(self.next_job_id)
        self.next_job_id += 1
        self.submitted_steps.append(submission.step_key)
        self.submissions[submission.attempt_id] = submission
        self.jobs[job_id] = {
            "submission": submission,
            "state": "queued",
            "raw_state": "PENDING",
            "exit_code": "0:0",
            "stale": False,
            "error_code": None,
            "identity_matches": True,
        }
        return job_id

    def adopt_submission(self, submission, job_id="71999"):
        self.submissions[submission.attempt_id] = submission
        self.jobs[job_id] = {
            "submission": submission,
            "state": "queued",
            "raw_state": "PENDING",
            "exit_code": "0:0",
            "stale": False,
            "error_code": None,
            "identity_matches": True,
        }
        self.receipts[(submission.workflow_id, submission.attempt_id)] = job_id
        return job_id

    def write_job_receipt(self, workflow_id, attempt_id, job_id):
        key = (workflow_id, attempt_id)
        current = self.receipts.get(key)
        if current is not None and current != job_id:
            raise ValueError("receipt mismatch")
        self.receipts[key] = job_id

    def read_job_receipt(self, workflow_id, attempt_id):
        try:
            return self.receipts[(workflow_id, attempt_id)]
        except KeyError as exc:
            raise ValueError("receipt missing") from exc

    def set_state(
        self,
        attempt_id,
        state,
        *,
        raw_state=None,
        exit_code=None,
        stale=False,
        error_code=None,
        identity_matches=True,
    ):
        submission = self.submissions[attempt_id]
        job_id = self.receipts[(submission.workflow_id, attempt_id)]
        job = self.jobs[job_id]
        job.update(
            state=state,
            raw_state=raw_state,
            exit_code=exit_code,
            stale=stale,
            error_code=error_code,
            identity_matches=identity_matches,
        )

    def observe(self, job_id):
        job = self.jobs[job_id]
        submission = job["submission"]
        identity_matches = job["identity_matches"]
        now = datetime.now(timezone.utc)
        terminal = job["state"] in {"succeeded", "failed", "cancelled"}
        return SlurmJobObservation(
            job_id=job_id,
            raw_state=job["raw_state"],
            state=job["state"],
            exit_code=job["exit_code"],
            reason=None,
            source="fake",
            job_name=submission.job_name if identity_matches else "foreign-job",
            working_directory=(
                str(submission.attempt_directory.resolve())
                if identity_matches
                else str(self.root / "foreign")
            ),
            comment=submission.comment if identity_matches else "foreign-comment",
            user_name="pb23030683" if identity_matches else "foreign-user",
            node_list="anode01",
            observed_at=now,
            started_at=now if job["state"] == "running" else None,
            finished_at=now if terminal else None,
            stale=job["stale"],
            error_code=job["error_code"],
            payload_sha256="f" * 64,
        )


class FakeAcceptancePolicy:
    def __init__(self):
        self.failures = {}
        self.exceptions = {}
        self.calls = []

    def __call__(
        self,
        attempt_directory,
        stage,
        *,
        scheduler_state,
        scheduler_exit_code,
    ):
        self.calls.append(
            (Path(attempt_directory), stage, scheduler_state, scheduler_exit_code)
        )
        if stage in self.exceptions:
            raise self.exceptions[stage]
        reason_code = self.failures.get(stage)
        if reason_code is not None:
            return AcceptanceReport(
                accepted=False,
                reason_code=reason_code,
                checks=(
                    {
                        "name": "electronic_convergence",
                        "passed": False,
                        "reason_code": reason_code,
                    },
                ),
                measurements={},
                artifacts=(),
            )
        output_name = {
            "relax": "CONTCAR",
            "scf": "CHGCAR",
            "band": "EIGENVAL",
            "dos": "DOSCAR",
        }[stage]
        output_bytes = f"{stage}:{output_name}\n".encode("ascii")
        (Path(attempt_directory) / output_name).write_bytes(output_bytes)
        return AcceptanceReport(
            accepted=True,
            reason_code=None,
            checks=(
                {"name": "stage", "passed": True},
                {"name": f"artifact:{output_name}", "passed": True},
            ),
            measurements={},
            artifacts=(
                {
                    "name": output_name,
                    "sha256": hashlib.sha256(output_bytes).hexdigest(),
                    "size_bytes": len(output_bytes),
                },
            ),
        )


class CompetitionCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.workflow_root = self.root / "workflow-data"
        self.engine = create_engine(
            f"sqlite:///{self.root / 'workflow.sqlite'}"
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=1000")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.SessionLocal() as session:
            owner = User(
                email="coordinator-owner@example.com",
                password_hash="hash",
                name="coordinator-owner",
                alias="",
                role="operator",
            )
            session.add(owner)
            session.commit()
            self.owner_id = owner.id

        self.vasp_script = self.root / "vasp-stage.slurm"
        self.vasp_script.write_text("#!/bin/bash\n", encoding="utf-8")
        self.probe_script = self.root / "probe.slurm"
        self.probe_script.write_text("#!/bin/bash\n", encoding="utf-8")
        self.slurm = FakeSlurm(self.workflow_root)
        self.reconciler = CompetitionReconciler(
            slurm=self.slurm,
            probe_script=self.probe_script,
            vasp_script=self.vasp_script,
            slurm_user="pb23030683",
        )
        self.acceptance = FakeAcceptancePolicy()
        self.prepared_steps = []
        self.workflow_id = self.create_workflow()
        self.coordinator = self.new_coordinator()

    def create_workflow(self, *, status="validated"):
        workflow_id = str(uuid.uuid4())
        with self.SessionLocal() as session:
            run = WorkflowRun(
                id=workflow_id,
                owner_id=self.owner_id,
                template_version="mos2_v1",
                material="MoS2",
                source_kind="builtin",
                status=status,
                input_sha256="a" * 64,
                release_commit="b" * 40,
                metadata_json={
                    "normalized_payload": {
                        "parameters": {},
                        "source_kind": "builtin",
                        "steps": list(FIXED_STEPS),
                        "template_version": "mos2_v1",
                    }
                },
            )
            session.add(run)
            session.flush()
            for position, step_key in enumerate(FIXED_STEPS):
                session.add(
                    WorkflowStep(
                        workflow_id=workflow_id,
                        step_key=step_key,
                        position=position,
                        status="waiting",
                        parameters_json={},
                    )
                )
            session.add(
                WorkflowEvent(
                    workflow_id=workflow_id,
                    sequence=1,
                    event_type="workflow_validated",
                    payload_json={"input_sha256": run.input_sha256},
                )
            )
            session.commit()
        return workflow_id

    def prepare_inputs(self, session, workflow_root, **values):
        self.prepared_steps.append(values["step_key"])
        return self.slurm.prepare_attempt_directory(
            values["workflow_id"], values["attempt_id"]
        )

    def new_coordinator(self, *, acceptance=None, prepare_inputs=None):
        return CompetitionCoordinator(
            session_factory=self.SessionLocal,
            reconciler=self.reconciler,
            workflow_root=self.workflow_root,
            vasp_script=self.vasp_script,
            prepare_inputs=prepare_inputs or self.prepare_inputs,
            accept_attempt=acceptance or self.acceptance,
            batch_limit=16,
        )

    def seed_stage5_inputs(self):
        names = {
            "relax": ("INCAR", "KPOINTS", "POSCAR", "POTCAR.spec"),
            "scf": ("INCAR", "KPOINTS", "POTCAR.spec"),
            "band": ("INCAR", "KPOINTS", "POTCAR.spec"),
            "dos": ("INCAR", "KPOINTS", "POTCAR.spec"),
        }
        with self.SessionLocal() as session:
            for step_key, filenames in names.items():
                for filename in filenames:
                    content = f"{step_key}:{filename}\n".encode("ascii")
                    relative_path = f"{self.workflow_id}/generated/{step_key}/{filename}"
                    path = self.workflow_root / relative_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    session.add(
                        WorkflowFile(
                            id=str(uuid.uuid4()),
                            workflow_id=self.workflow_id,
                            attempt_id=None,
                            owner_id=self.owner_id,
                            relative_path=relative_path,
                            size_bytes=len(content),
                            sha256=hashlib.sha256(content).hexdigest(),
                            source_kind="generated",
                            metadata_json={
                                "logical_path": f"{step_key}/{filename}",
                                "step_key": step_key,
                            },
                        )
                    )
            session.commit()

    def latest_attempt(self, step_key, workflow_id=None):
        workflow_id = workflow_id or self.workflow_id
        with self.SessionLocal() as session:
            return session.scalar(
                select(WorkflowAttempt)
                .join(WorkflowStep, WorkflowStep.id == WorkflowAttempt.step_id)
                .where(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowStep.step_key == step_key,
                )
                .order_by(WorkflowAttempt.attempt_number.desc())
            )

    def attempt_count(self, step_key=None, workflow_id=None):
        workflow_id = workflow_id or self.workflow_id
        with self.SessionLocal() as session:
            statement = (
                select(func.count())
                .select_from(WorkflowAttempt)
                .join(WorkflowStep, WorkflowStep.id == WorkflowAttempt.step_id)
                .where(WorkflowStep.workflow_id == workflow_id)
            )
            if step_key is not None:
                statement = statement.where(WorkflowStep.step_key == step_key)
            return session.scalar(statement)

    def active_count(self, workflow_id=None):
        workflow_id = workflow_id or self.workflow_id
        with self.SessionLocal() as session:
            return session.scalar(
                select(func.count())
                .select_from(WorkflowAttempt)
                .join(WorkflowStep, WorkflowStep.id == WorkflowAttempt.step_id)
                .where(
                    WorkflowStep.workflow_id == workflow_id,
                    WorkflowAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
                )
            )

    def step_statuses(self, workflow_id=None):
        workflow_id = workflow_id or self.workflow_id
        with self.SessionLocal() as session:
            rows = session.execute(
                select(WorkflowStep.step_key, WorkflowStep.status).where(
                    WorkflowStep.workflow_id == workflow_id
                )
            ).all()
            return dict(rows)

    def run_status(self, workflow_id=None):
        workflow_id = workflow_id or self.workflow_id
        with self.SessionLocal() as session:
            return session.get(WorkflowRun, workflow_id).status

    def complete(self, step_key, *, accepted=True, reason="electronic_not_converged"):
        attempt = self.latest_attempt(step_key)
        if not accepted:
            self.acceptance.failures[step_key] = reason
        self.slurm.set_state(
            attempt.id,
            "succeeded",
            raw_state="COMPLETED",
            exit_code="0:0",
        )
        self.coordinator.tick_once()

    def start(self, workflow_id=None):
        return self.coordinator.start(
            workflow_id or self.workflow_id,
            self.owner_id,
        )

    def test_next_eligible_step_is_the_fixed_branch_policy(self):
        states = {step: "waiting" for step in FIXED_STEPS}
        self.assertEqual("relax", next_eligible_step(states))
        states["relax"] = "succeeded"
        self.assertEqual("scf", next_eligible_step(states))
        states["scf"] = "succeeded"
        self.assertEqual("band", next_eligible_step(states))
        states["band"] = "failed"
        self.assertEqual("dos", next_eligible_step(states))
        states["band"] = "scientific_failed"
        self.assertEqual("dos", next_eligible_step(states))
        states["band"] = "cancelled"
        self.assertIsNone(next_eligible_step(states))

    def test_success_workflow_submits_one_job_at_a_time_and_persists_acceptance(self):
        started = self.start()
        self.assertEqual("relax", started.step_key)
        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual(1, self.active_count())

        self.complete("relax")
        self.assertEqual(["relax", "scf"], self.slurm.submitted_steps)
        self.assertEqual(1, self.active_count())
        with self.SessionLocal() as session:
            relax = self.latest_attempt("relax")
            persisted = session.get(WorkflowAttempt, relax.id)
            metadata = json.loads(persisted.metadata_json)
            report = metadata["scientific_acceptance"]
            expected_hash = hashlib.sha256(
                canonical_json(report).encode("utf-8")
            ).hexdigest()
            self.assertEqual(expected_hash, metadata["scientific_acceptance_sha256"])
            output = session.scalar(
                select(WorkflowFile).where(
                    WorkflowFile.attempt_id == relax.id,
                    WorkflowFile.source_kind == "attempt_output",
                )
            )
            self.assertEqual("CONTCAR", json.loads(output.metadata_json)["logical_path"])

        self.complete("scf")
        self.assertEqual(["relax", "scf", "band"], self.slurm.submitted_steps)
        self.assertEqual(1, self.active_count())
        self.complete("band")
        self.assertEqual(
            ["relax", "scf", "band", "dos"], self.slurm.submitted_steps
        )
        self.assertEqual(1, self.active_count())
        self.complete("dos")

        self.assertEqual("succeeded", self.run_status())
        self.assertEqual({step: "succeeded" for step in FIXED_STEPS}, self.step_statuses())
        self.assertEqual(0, self.active_count())
        with self.SessionLocal() as session:
            events = session.scalars(
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_id == self.workflow_id)
                .order_by(WorkflowEvent.sequence)
            ).all()
            self.assertEqual(list(range(1, len(events) + 1)), [row.sequence for row in events])
            accepted = [
                row for row in events if row.event_type == "scientific_acceptance_completed"
            ]
            self.assertEqual(4, len(accepted))

    def test_accepted_outputs_feed_real_scf_band_and_dos_input_preparation(self):
        self.seed_stage5_inputs()
        coordinator = self.new_coordinator(prepare_inputs=prepare_attempt_inputs)
        coordinator.start(self.workflow_id, self.owner_id)

        relax = self.latest_attempt("relax")
        self.slurm.set_state(
            relax.id,
            "succeeded",
            raw_state="COMPLETED",
            exit_code="0:0",
        )
        first_tick = coordinator.tick_once()
        with self.SessionLocal() as session:
            output = session.scalar(
                select(WorkflowFile).where(
                    WorkflowFile.attempt_id == relax.id,
                    WorkflowFile.source_kind == "attempt_output",
                )
            )
            self.assertIs(json.loads(output.metadata_json).get("accepted"), True)
        self.assertEqual(0, first_tick.failures)
        scf = self.latest_attempt("scf")
        relax_contcar = Path(relax.working_directory) / "CONTCAR"
        self.assertEqual(relax_contcar.read_bytes(), (Path(scf.working_directory) / "POSCAR").read_bytes())

        self.slurm.set_state(
            scf.id,
            "succeeded",
            raw_state="COMPLETED",
            exit_code="0:0",
        )
        self.assertEqual(0, coordinator.tick_once().failures)
        band = self.latest_attempt("band")
        scf_directory = Path(scf.working_directory)
        band_directory = Path(band.working_directory)
        self.assertEqual((scf_directory / "POSCAR").read_bytes(), (band_directory / "POSCAR").read_bytes())
        self.assertEqual((scf_directory / "CHGCAR").read_bytes(), (band_directory / "CHGCAR").read_bytes())

        self.slurm.set_state(
            band.id,
            "succeeded",
            raw_state="COMPLETED",
            exit_code="0:0",
        )
        self.assertEqual(0, coordinator.tick_once().failures)
        dos = self.latest_attempt("dos")
        dos_directory = Path(dos.working_directory)
        self.assertEqual((scf_directory / "POSCAR").read_bytes(), (dos_directory / "POSCAR").read_bytes())
        self.assertEqual((scf_directory / "CHGCAR").read_bytes(), (dos_directory / "CHGCAR").read_bytes())

    def test_scf_scientific_failure_blocks_band_and_dos_without_artifacts(self):
        self.start()
        self.complete("relax")
        self.complete("scf", accepted=False)

        self.assertEqual(["relax", "scf"], self.slurm.submitted_steps)
        self.assertEqual(2, self.attempt_count())
        self.assertEqual(0, self.attempt_count("band"))
        self.assertEqual(0, self.attempt_count("dos"))
        statuses = self.step_statuses()
        self.assertEqual("scientific_failed", statuses["scf"])
        self.assertEqual("blocked", statuses["band"])
        self.assertEqual("blocked", statuses["dos"])
        self.assertEqual("failed", self.run_status())
        attempt_dirs = list(self.workflow_root.glob("*/attempts/*"))
        self.assertEqual(2, len(attempt_dirs))

    def test_band_scheduler_failure_still_permits_dos_and_run_remains_failed(self):
        self.start()
        self.complete("relax")
        self.complete("scf")
        band = self.latest_attempt("band")
        self.slurm.set_state(
            band.id,
            "failed",
            raw_state="FAILED",
            exit_code="1:0",
        )
        self.coordinator.tick_once()

        self.assertEqual(
            ["relax", "scf", "band", "dos"], self.slurm.submitted_steps
        )
        self.complete("dos")
        statuses = self.step_statuses()
        self.assertEqual("failed", statuses["band"])
        self.assertEqual("succeeded", statuses["dos"])
        self.assertEqual("failed", self.run_status())

    def test_band_scientific_failure_still_permits_dos(self):
        self.start()
        self.complete("relax")
        self.complete("scf")
        self.complete("band", accepted=False)

        self.assertEqual(
            ["relax", "scf", "band", "dos"], self.slurm.submitted_steps
        )
        self.complete("dos")
        self.assertEqual("scientific_failed", self.step_statuses()["band"])
        self.assertEqual("succeeded", self.step_statuses()["dos"])
        self.assertEqual("failed", self.run_status())

    def test_user_cancellation_blocks_every_later_submission(self):
        self.start()
        relax = self.latest_attempt("relax")
        with self.SessionLocal() as session:
            attempt = session.get(WorkflowAttempt, relax.id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            attempt.status = "cancelled"
            step.status = "cancelled"
            run.status = "cancelled"
            session.commit()

        self.coordinator.tick_once()
        self.coordinator.tick_once()

        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual(1, self.attempt_count())
        self.assertEqual("cancelled", self.run_status())

    def test_committed_cancellation_intent_blocks_acceptance_and_advance(self):
        self.start()
        relax = self.latest_attempt("relax")
        self.slurm.set_state(
            relax.id,
            "succeeded",
            raw_state="COMPLETED",
            exit_code="0:0",
        )
        with self.SessionLocal() as session:
            outcome = self.reconciler.reconcile_attempt(session, relax.id)
            self.assertEqual("awaiting_acceptance", outcome.status)
            attempt = session.get(WorkflowAttempt, relax.id)
            metadata = json.loads(attempt.metadata_json)
            metadata["cancel_result"] = {
                "result": "requested",
                "observed_at": datetime.now(timezone.utc).isoformat(),
            }
            attempt.metadata_json = metadata
            session.commit()

        self.coordinator.tick_once()

        self.assertEqual("cancelled", self.latest_attempt("relax").status)
        self.assertEqual([], self.acceptance.calls)
        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual(0, self.attempt_count("scf"))
        self.assertEqual("cancelled", self.run_status())
        with self.SessionLocal() as session:
            self.assertEqual(
                0,
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowFile)
                    .where(WorkflowFile.attempt_id == relax.id)
                ),
            )
            self.assertEqual(
                0,
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowEvent)
                    .where(
                        WorkflowEvent.workflow_id == self.workflow_id,
                        WorkflowEvent.event_type == "scientific_acceptance_completed",
                    )
                ),
            )

    def test_concurrent_cancel_commit_wins_over_stale_reconciliation(self):
        self.start()
        relax = self.latest_attempt("relax")
        self.slurm.set_state(
            relax.id,
            "running",
            raw_state="RUNNING",
            exit_code="0:0",
        )

        reconciliation_observed = threading.Event()
        release_reconciliation = threading.Event()
        original_observe = self.slurm.observe
        cancelled_jobs = []

        def interleaved_observe(job_id):
            observation = original_observe(job_id)
            if threading.current_thread().name != "stale-reconciliation":
                return observation
            reconciliation_observed.set()
            if not release_reconciliation.wait(timeout=5):
                raise TimeoutError("concurrent cancellation did not commit")
            now = datetime.now(timezone.utc)
            return replace(
                observation,
                raw_state="COMPLETED",
                state="succeeded",
                exit_code="0:0",
                observed_at=now,
                finished_at=now,
            )

        self.slurm.observe = interleaved_observe
        self.slurm.inspect_job = original_observe
        self.slurm.cancel = cancelled_jobs.append
        tick_results = []

        worker = threading.Thread(
            target=lambda: tick_results.append(self.coordinator.tick_once()),
            name="stale-reconciliation",
        )
        worker.start()
        self.assertTrue(reconciliation_observed.wait(timeout=5))
        try:
            with self.SessionLocal() as session:
                cancellation = self.reconciler.cancel_attempt(
                    session,
                    self.workflow_id,
                    relax.id,
                )
        finally:
            release_reconciliation.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(("requested", "cancelling"), (cancellation.result, cancellation.status))
        self.assertEqual([relax.slurm_job_id], cancelled_jobs)
        self.assertEqual(1, len(tick_results))
        self.assertEqual(0, tick_results[0].failures)
        with self.SessionLocal() as session:
            attempt = session.get(WorkflowAttempt, relax.id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            metadata = json.loads(attempt.metadata_json)
            cancel_result = metadata.get("cancel_result")
            self.assertEqual(
                "requested",
                cancel_result.get("result") if isinstance(cancel_result, dict) else None,
            )
            self.assertEqual(
                ("cancelling", "cancelling", "cancelling"),
                (attempt.status, step.status, run.status),
            )
        self.assertEqual([], self.acceptance.calls)
        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual(0, self.attempt_count("scf"))

    def test_repeated_ticks_two_instances_and_duplicate_start_cannot_duplicate(self):
        first = self.start()
        second = self.new_coordinator().start(self.workflow_id, self.owner_id)
        for _ in range(3):
            self.coordinator.tick_once()
            self.new_coordinator().tick_once()

        self.assertEqual(first.attempt_id, second.attempt_id)
        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual(1, self.attempt_count("relax"))
        self.assertEqual(1, self.active_count())

    def test_unknown_stale_and_ownership_mismatch_never_advance(self):
        cases = (
            {
                "state": "unknown",
                "raw_state": None,
                "exit_code": None,
                "stale": True,
                "error_code": "scheduler_record_unavailable",
            },
            {
                "state": "queued",
                "raw_state": "PENDING",
                "exit_code": "0:0",
                "identity_matches": False,
            },
        )
        for index, values in enumerate(cases):
            workflow_id = self.workflow_id if index == 0 else self.create_workflow()
            self.start(workflow_id)
            attempt = self.latest_attempt("relax", workflow_id)
            self.slurm.set_state(attempt.id, **values)
            self.coordinator.tick_once()
            self.assertEqual(0, self.attempt_count("scf", workflow_id))

    def test_unknown_attempt_retries_observation_but_advances_only_after_trust(self):
        self.start()
        relax = self.latest_attempt("relax")
        self.slurm.set_state(
            relax.id,
            "unknown",
            raw_state=None,
            exit_code=None,
            stale=True,
            error_code="scheduler_record_unavailable",
        )
        self.coordinator.tick_once()
        self.assertEqual(0, self.attempt_count("scf"))

        self.slurm.set_state(
            relax.id,
            "succeeded",
            raw_state="COMPLETED",
            exit_code="0:0",
        )
        self.coordinator.tick_once()

        self.assertEqual(["relax", "scf"], self.slurm.submitted_steps)

    def test_acceptance_exception_never_advances(self):
        self.acceptance.exceptions["relax"] = RuntimeError("parser failed")
        self.start()
        relax = self.latest_attempt("relax")
        self.slurm.set_state(
            relax.id,
            "succeeded",
            raw_state="COMPLETED",
            exit_code="0:0",
        )

        self.coordinator.tick_once()
        self.coordinator.tick_once()

        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual("awaiting_acceptance", self.latest_attempt("relax").status)
        self.assertEqual(0, self.attempt_count("scf"))

    def test_restart_recovers_preparing_attempt(self):
        with self.SessionLocal() as session:
            claim = self.reconciler.claim_attempt(
                session,
                self.workflow_id,
                step_key="relax",
                runner_kind="vasp",
                runner_mode="relax",
                script_path=self.vasp_script,
                claimable_run_statuses=frozenset({"validated"}),
            )
        self.assertEqual("preparing", claim.status)

        self.new_coordinator().tick_once()

        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual("queued", self.latest_attempt("relax").status)

    def test_vasp_claim_leaves_the_target_unpublished_for_input_materialization(self):
        with self.SessionLocal() as session:
            claim = self.reconciler.claim_attempt(
                session,
                self.workflow_id,
                step_key="relax",
                runner_kind="vasp",
                runner_mode="relax",
                script_path=self.vasp_script,
                claimable_run_statuses=frozenset({"validated"}),
            )

        self.assertFalse(claim.submission.attempt_directory.exists())

    def test_restart_recovers_submitting_without_second_sbatch(self):
        with self.SessionLocal() as session:
            claim = self.reconciler.claim_attempt(
                session,
                self.workflow_id,
                step_key="relax",
                runner_kind="vasp",
                runner_mode="relax",
                script_path=self.vasp_script,
                claimable_run_statuses=frozenset({"validated"}),
            )
        with self.SessionLocal() as session:
            attempt = session.get(WorkflowAttempt, claim.attempt_id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            attempt.status = step.status = run.status = "submitting"
            session.commit()
        job_id = self.slurm.adopt_submission(claim.submission)

        self.new_coordinator().tick_once()

        self.assertEqual([], self.slurm.submitted_steps)
        recovered = self.latest_attempt("relax")
        self.assertEqual(("queued", job_id), (recovered.status, recovered.slurm_job_id))

    def test_restart_fails_closed_when_submitting_has_no_job_receipt(self):
        with self.SessionLocal() as session:
            claim = self.reconciler.claim_attempt(
                session,
                self.workflow_id,
                step_key="relax",
                runner_kind="vasp",
                runner_mode="relax",
                script_path=self.vasp_script,
                claimable_run_statuses=frozenset({"validated"}),
            )
            self.prepare_inputs(
                session,
                self.workflow_root,
                owner_id=self.owner_id,
                workflow_id=self.workflow_id,
                step_key="relax",
                attempt_id=claim.attempt_id,
                template_version="mos2_v1",
                release_commit="b" * 40,
            )
            promoted = self.reconciler.promote_claim(
                session,
                claim,
                claimable_run_statuses=frozenset({"validated"}),
                event_type="submission_started",
            )
        self.assertEqual("submitting", promoted.status)
        self.assertEqual([], self.slurm.submitted_steps)
        self.assertFalse((promoted.submission.attempt_directory / "job-id.receipt").exists())

        first_tick = self.new_coordinator().tick_once()
        second_tick = self.new_coordinator().tick_once()

        self.assertEqual(1, first_tick.failures)
        self.assertEqual(0, second_tick.failures)
        self.assertEqual([], self.slurm.submitted_steps)
        with self.SessionLocal() as session:
            attempt = session.get(WorkflowAttempt, promoted.attempt_id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            self.assertEqual(
                ("submission_failed", "failed", "failed"),
                (attempt.status, step.status, run.status),
            )
            event_row = session.scalar(
                select(WorkflowEvent)
                .where(WorkflowEvent.event_type == "submission_failed")
                .order_by(WorkflowEvent.sequence.desc())
            )
            self.assertEqual(
                "submission_receipt_missing",
                json.loads(event_row.payload_json)["reason_code"],
            )

    def test_restart_reconciles_queued_and_running_attempts(self):
        for desired_state in ("queued", "running"):
            with self.subTest(desired_state=desired_state):
                workflow_id = self.create_workflow()
                self.start(workflow_id)
                attempt = self.latest_attempt("relax", workflow_id)
                if desired_state == "running":
                    self.slurm.set_state(
                        attempt.id,
                        "running",
                        raw_state="RUNNING",
                        exit_code="0:0",
                    )
                before = list(self.slurm.submitted_steps)
                self.new_coordinator().tick_once()
                self.assertEqual(before, self.slurm.submitted_steps)
                self.assertEqual(desired_state, self.latest_attempt("relax", workflow_id).status)

    def test_restart_accepts_awaiting_acceptance_and_advances(self):
        self.start()
        relax = self.latest_attempt("relax")
        self.slurm.set_state(
            relax.id,
            "succeeded",
            raw_state="COMPLETED",
            exit_code="0:0",
        )
        with self.SessionLocal() as session:
            outcome = self.reconciler.reconcile_attempt(session, relax.id)
        self.assertEqual("awaiting_acceptance", outcome.status)

        self.new_coordinator().tick_once()

        self.assertEqual(["relax", "scf"], self.slurm.submitted_steps)
        self.assertEqual("succeeded", self.latest_attempt("relax").status)

    def test_acceptance_commit_failure_creates_no_output_event_or_next_job(self):
        self.start()
        relax = self.latest_attempt("relax")
        self.slurm.set_state(
            relax.id,
            "succeeded",
            raw_state="COMPLETED",
            exit_code="0:0",
        )
        original_commit = Session.commit
        commit_calls = 0

        def fail_acceptance_commit(session):
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 2:
                raise RuntimeError("database unavailable")
            return original_commit(session)

        with mock.patch.object(Session, "commit", fail_acceptance_commit):
            self.coordinator.tick_once()

        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual(0, self.attempt_count("scf"))
        self.assertEqual("awaiting_acceptance", self.latest_attempt("relax").status)
        with self.SessionLocal() as session:
            self.assertEqual(
                0,
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowFile)
                    .where(WorkflowFile.attempt_id == relax.id)
                ),
            )
            self.assertEqual(
                0,
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowEvent)
                    .where(
                        WorkflowEvent.workflow_id == self.workflow_id,
                        WorkflowEvent.event_type == "scientific_acceptance_completed",
                    )
                ),
            )

    def test_start_rejects_non_owner_and_nonvalidated_workflow(self):
        with self.assertRaises(CoordinatorError) as non_owner:
            self.coordinator.start(self.workflow_id, self.owner_id + 1)
        self.assertEqual("workflow_not_found", non_owner.exception.code)

        invalid = self.create_workflow(status="draft")
        with self.assertRaises(CoordinatorError) as unvalidated:
            self.coordinator.start(invalid, self.owner_id)
        self.assertEqual("workflow_not_startable", unvalidated.exception.code)

    def test_start_revalidates_fixed_material_template_and_source_provenance(self):
        cases = (
            ("material", "MoSe2"),
            ("template_version", "foreign_v1"),
            ("source_kind", "upload"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                workflow_id = self.create_workflow()
                with self.SessionLocal() as session:
                    run = session.get(WorkflowRun, workflow_id)
                    setattr(run, field, value)
                    session.commit()

                with self.assertRaises(CoordinatorError) as raised:
                    self.coordinator.start(workflow_id, self.owner_id)

                self.assertEqual("workflow_scope_invalid", raised.exception.code)
                self.assertEqual(0, self.attempt_count(workflow_id=workflow_id))
        self.assertEqual([], self.slurm.submitted_steps)
        self.assertEqual([], self.prepared_steps)
        self.assertEqual([], list(self.workflow_root.rglob("attempts")))

    def test_post_start_scope_mutation_blocks_scf_without_changing_accepted_relax(self):
        cases = ("material", "template_metadata", "source_metadata")
        for case in cases:
            with self.subTest(case=case):
                workflow_id = self.create_workflow()
                coordinator = self.new_coordinator()
                coordinator.start(workflow_id, self.owner_id)
                relax = self.latest_attempt("relax", workflow_id)
                submitted_before = len(self.slurm.submitted_steps)
                with self.SessionLocal() as session:
                    run = session.get(WorkflowRun, workflow_id)
                    if case == "material":
                        run.material = "MoSe2"
                    else:
                        metadata = json.loads(run.metadata_json)
                        field = "template_version" if case == "template_metadata" else "source_kind"
                        metadata["normalized_payload"][field] = "foreign"
                        run.metadata_json = metadata
                    session.commit()
                self.slurm.set_state(
                    relax.id,
                    "succeeded",
                    raw_state="COMPLETED",
                    exit_code="0:0",
                )

                first_tick = coordinator.tick_once()
                second_tick = coordinator.tick_once()

                self.assertEqual((0, 0), (first_tick.failures, second_tick.failures))
                self.assertEqual(submitted_before, len(self.slurm.submitted_steps))
                self.assertEqual("succeeded", self.latest_attempt("relax", workflow_id).status)
                self.assertEqual(0, self.attempt_count("scf", workflow_id))
                self.assertEqual("failed", self.run_status(workflow_id))
                self.assertEqual("blocked", self.step_statuses(workflow_id)["scf"])
                with self.SessionLocal() as session:
                    scope_events = list(
                        session.scalars(
                            select(WorkflowEvent).where(
                                WorkflowEvent.workflow_id == workflow_id,
                                WorkflowEvent.event_type == "workflow_scope_invalid",
                            )
                        )
                    )
                    self.assertEqual(
                        1,
                        len(scope_events),
                    )
                    self.assertEqual(
                        {"reason_code": "workflow_scope_invalid"},
                        json.loads(scope_events[0].payload_json),
                    )
                scf_directories = list(
                    (self.workflow_root / workflow_id / "attempts").glob("*")
                )
                self.assertEqual(1, len(scf_directories))

    def test_preparing_restart_scope_mutation_fails_before_input_or_submission(self):
        with self.SessionLocal() as session:
            claim = self.reconciler.claim_attempt(
                session,
                self.workflow_id,
                step_key="relax",
                runner_kind="vasp",
                runner_mode="relax",
                script_path=self.vasp_script,
                claimable_run_statuses=frozenset({"validated"}),
            )
        with self.SessionLocal() as session:
            run = session.get(WorkflowRun, self.workflow_id)
            run.material = "MoSe2"
            session.commit()

        first_tick = self.new_coordinator().tick_once()
        second_tick = self.new_coordinator().tick_once()

        self.assertEqual((0, 0), (first_tick.failures, second_tick.failures))
        self.assertEqual([], self.slurm.submitted_steps)
        self.assertFalse(claim.submission.attempt_directory.exists())
        with self.SessionLocal() as session:
            attempt = session.get(WorkflowAttempt, claim.attempt_id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            self.assertEqual(
                ("submission_failed", "failed", "failed"),
                (attempt.status, step.status, run.status),
            )
            self.assertEqual(
                1,
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowEvent)
                    .where(
                        WorkflowEvent.workflow_id == self.workflow_id,
                        WorkflowEvent.event_type == "workflow_scope_invalid",
                    )
                ),
            )

    def test_scope_mutation_after_claim_fails_before_input_preparation(self):
        original_claim = self.reconciler.claim_attempt

        def claim_then_mutate(*args, **kwargs):
            claim = original_claim(*args, **kwargs)
            with self.SessionLocal() as session:
                run = session.get(WorkflowRun, claim.workflow_id)
                run.material = "MoSe2"
                session.commit()
            return claim

        with mock.patch.object(
            self.reconciler,
            "claim_attempt",
            side_effect=claim_then_mutate,
        ):
            outcome = self.coordinator.start(self.workflow_id, self.owner_id)

        self.assertEqual("submission_failed", outcome.status)
        self.assertEqual([], self.prepared_steps)
        self.assertEqual([], self.slurm.submitted_steps)
        attempt = self.latest_attempt("relax")
        self.assertFalse(Path(attempt.working_directory).exists())
        self.assertEqual("submission_failed", attempt.status)

    def test_scope_mutation_during_input_preparation_fails_before_submission(self):
        def prepare_then_mutate(session, workflow_root, **values):
            prepared = self.prepare_inputs(session, workflow_root, **values)
            with self.SessionLocal() as mutation_session:
                run = mutation_session.get(WorkflowRun, values["workflow_id"])
                run.material = "MoSe2"
                mutation_session.commit()
            return prepared

        coordinator = self.new_coordinator(prepare_inputs=prepare_then_mutate)

        outcome = coordinator.start(self.workflow_id, self.owner_id)

        self.assertEqual("submission_failed", outcome.status)
        self.assertEqual(["relax"], self.prepared_steps)
        self.assertEqual([], self.slurm.submitted_steps)
        attempt = self.latest_attempt("relax")
        self.assertTrue(Path(attempt.working_directory).is_dir())
        self.assertEqual("submission_failed", attempt.status)


if __name__ == "__main__":
    unittest.main()
