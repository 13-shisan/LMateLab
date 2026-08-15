from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from database import Base
from models import User
from models_workflow import WorkflowAttempt, WorkflowEvent, WorkflowRun, WorkflowStep
from services.competition_reconcile import CompetitionReconciler, ReconcileError
from services.competition_slurm import (
    SlurmBinaries,
    SlurmClient,
    SlurmCommandTimeout,
    SlurmOutputTooLarge,
    SlurmSubmission,
)


class RecordingExecutor:
    def __init__(self, *, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


class SequenceExecutor:
    def __init__(self, *responses: subprocess.CompletedProcess):
        self.responses = list(responses)
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        if not self.responses:
            raise AssertionError(f"unexpected command: {argv}")
        response = self.responses.pop(0)
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=response.returncode,
            stdout=response.stdout,
            stderr=response.stderr,
        )


def response(*, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def fixture(name: str) -> bytes:
    path = Path(__file__).parent / "fixtures" / "fake_slurm" / name
    return path.read_bytes()


def fixed_binaries() -> SlurmBinaries:
    return SlurmBinaries(
        sbatch="/usr/bin/sbatch",
        squeue="/usr/bin/squeue",
        scontrol="/usr/bin/scontrol",
        sacct="/usr/bin/sacct",
        scancel="/usr/bin/scancel",
    )


class SlurmCommandContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.script = self.root / "probe.slurm"
        self.script.write_text("#!/bin/bash\n", encoding="utf-8")
        self.workflow_id = str(uuid.uuid4())
        self.attempt_id = str(uuid.uuid4())
        self.attempt_dir = self.root / "workflows" / self.workflow_id / "attempts" / self.attempt_id
        self.attempt_dir.mkdir(parents=True)

    def submission(self, *, mode: str = "success") -> SlurmSubmission:
        return SlurmSubmission(
            workflow_id=self.workflow_id,
            attempt_id=self.attempt_id,
            step_key="relax",
            attempt_number=1,
            attempt_directory=self.attempt_dir,
            script_path=self.script,
            probe_mode=mode,
        )

    def client(self, executor: RecordingExecutor, *, max_output_bytes: int = 4096) -> SlurmClient:
        return SlurmClient(
            binaries=fixed_binaries(),
            executor=executor,
            timeout_seconds=3.0,
            max_output_bytes=max_output_bytes,
            allowed_scripts=(self.script,),
            workflow_root=self.root / "workflows",
        )

    def test_binaries_must_be_fixed_absolute_posix_paths(self):
        with self.assertRaises(ValueError):
            SlurmBinaries(sbatch="sbatch")
        with self.assertRaises(ValueError):
            SlurmBinaries(sbatch="/usr/bin/../tmp/sbatch")

    def test_test_only_builds_fixed_argv_without_a_shell(self):
        executor = RecordingExecutor(stdout=b"sbatch: Job 123 to start later\n")
        client = self.client(executor)

        result = client.test_submission(self.submission())

        self.assertEqual("sbatch: Job 123 to start later", result.stdout)
        self.assertEqual(1, len(executor.calls))
        argv, kwargs = executor.calls[0]
        self.assertEqual("/usr/bin/sbatch", argv[0])
        self.assertEqual("--test-only", argv[1])
        self.assertIn("--parsable", argv)
        self.assertIn(f"--chdir={self.attempt_dir}", argv)
        self.assertIn(f"--output={self.attempt_dir / 'stdout.log'}", argv)
        self.assertIn(f"--error={self.attempt_dir / 'stderr.log'}", argv)
        self.assertIn(
            f"--comment=lmatelab:workflow={self.workflow_id};attempt={self.attempt_id}",
            argv,
        )
        self.assertIn("--job-name=lmatelab-", " ".join(argv))
        self.assertEqual(
            [str(self.script), "success", self.workflow_id, self.attempt_id],
            argv[-4:],
        )
        self.assertIs(False, kwargs["shell"])
        self.assertIs(False, kwargs["check"])
        self.assertEqual(subprocess.PIPE, kwargs["stdout"])
        self.assertEqual(subprocess.PIPE, kwargs["stderr"])
        self.assertEqual(3.0, kwargs["timeout"])

    def test_submit_accepts_only_a_numeric_parsable_job_id(self):
        executor = RecordingExecutor(stdout=b"12345;training\n")
        client = self.client(executor)
        self.assertEqual("12345", client.submit(self.submission()))

        for output in (b"", b"12345 extra\n", b"abc;training\n", b"-1\n"):
            with self.subTest(output=output):
                invalid = self.client(RecordingExecutor(stdout=output))
                with self.assertRaises(ValueError):
                    invalid.submit(self.submission())

    def test_timeout_is_normalized_without_exposing_command_arguments(self):
        class TimeoutExecutor:
            def __call__(self, argv, **kwargs):
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        client = SlurmClient(
            binaries=fixed_binaries(),
            executor=TimeoutExecutor(),
            timeout_seconds=0.5,
            allowed_scripts=(self.script,),
            workflow_root=self.root / "workflows",
        )
        with self.assertRaisesRegex(SlurmCommandTimeout, "sbatch timed out") as raised:
            client.submit(self.submission())
        self.assertNotIn(self.workflow_id, str(raised.exception))
        self.assertNotIn(str(self.attempt_dir), str(raised.exception))

    def test_stdout_and_stderr_are_bounded(self):
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream):
                payload = {"stdout": b"", "stderr": b""}
                payload[stream] = b"x" * 65
                client = self.client(RecordingExecutor(**payload), max_output_bytes=64)
                with self.assertRaises(SlurmOutputTooLarge):
                    client.test_submission(self.submission())


class SlurmFilesystemBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.workflow_root = self.root / "workflow-data"
        self.workflow_id = str(uuid.uuid4())
        self.attempt_id = str(uuid.uuid4())
        self.client = SlurmClient(
            binaries=fixed_binaries(),
            executor=RecordingExecutor(),
            workflow_root=self.workflow_root,
            max_log_tail_bytes=8,
        )

    def test_attempt_directory_is_private_and_derived_only_from_canonical_ids(self):
        attempt_dir = self.client.prepare_attempt_directory(
            self.workflow_id,
            self.attempt_id,
        )

        self.assertEqual(
            self.workflow_root / self.workflow_id / "attempts" / self.attempt_id,
            attempt_dir,
        )
        self.assertTrue(attempt_dir.is_dir())
        if os.name == "posix":
            self.assertEqual(0, attempt_dir.stat().st_mode & 0o077)

        for invalid in ("../escape", "/tmp/escape", "not-a-uuid"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.client.prepare_attempt_directory(invalid, self.attempt_id)

    def test_submission_rejects_traversal_sibling_prefix_and_absolute_paths(self):
        script = self.root / "probe.slurm"
        script.write_text("#!/bin/bash\n", encoding="utf-8")
        client = SlurmClient(
            binaries=fixed_binaries(),
            executor=RecordingExecutor(stdout=b"41010\n"),
            workflow_root=self.workflow_root,
            allowed_scripts=(script,),
        )
        expected = client.prepare_attempt_directory(self.workflow_id, self.attempt_id)
        candidates = (
            expected / ".." / "escape",
            Path(f"{self.workflow_root}-sibling") / self.workflow_id / "attempts" / self.attempt_id,
            self.root / "absolute-outside" / self.attempt_id,
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                candidate.mkdir(parents=True, exist_ok=True)
                submission = SlurmSubmission(
                    workflow_id=self.workflow_id,
                    attempt_id=self.attempt_id,
                    step_key="relax",
                    attempt_number=1,
                    attempt_directory=candidate,
                    script_path=script,
                    probe_mode="success",
                )
                with self.assertRaises(ValueError):
                    client.submit(submission)

    def test_attempt_directory_symlink_is_rejected(self):
        expected = self.workflow_root / self.workflow_id / "attempts" / self.attempt_id
        expected.parent.mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        try:
            expected.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            if os.name != "nt":
                self.skipTest(f"directory symlinks unavailable: {exc}")
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(expected), str(outside)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if created.returncode != 0:
                self.skipTest("directory links unavailable")

        with self.assertRaises(ValueError):
            self.client.prepare_attempt_directory(self.workflow_id, self.attempt_id)

    def test_job_receipt_is_atomic_private_and_validated(self):
        attempt_dir = self.client.prepare_attempt_directory(self.workflow_id, self.attempt_id)

        receipt = self.client.write_job_receipt(self.workflow_id, self.attempt_id, "41011")

        self.assertEqual(attempt_dir / "job-id.receipt", receipt)
        self.assertEqual("41011\n", receipt.read_text(encoding="ascii"))
        if os.name == "posix":
            self.assertEqual(0, receipt.stat().st_mode & 0o077)
        self.assertEqual([], list(attempt_dir.glob(".job-id.receipt.*.tmp")))
        self.assertEqual(
            receipt,
            self.client.write_job_receipt(self.workflow_id, self.attempt_id, "41011"),
        )
        with self.assertRaises(ValueError):
            self.client.write_job_receipt(self.workflow_id, self.attempt_id, "41012")
        self.assertEqual("41011\n", receipt.read_text(encoding="ascii"))
        with self.assertRaises(ValueError):
            self.client.write_job_receipt(self.workflow_id, self.attempt_id, "41011;bad")

    def test_log_reads_are_name_allowlisted_and_tail_bounded(self):
        attempt_dir = self.client.prepare_attempt_directory(self.workflow_id, self.attempt_id)
        (attempt_dir / "stdout.log").write_bytes(b"0123456789")
        (attempt_dir / "stderr.log").write_bytes(b"abcdefghij")

        self.assertEqual("23456789", self.client.read_log_tail(self.workflow_id, self.attempt_id, "stdout"))
        self.assertEqual("cdefghij", self.client.read_log_tail(self.workflow_id, self.attempt_id, "stderr"))
        for invalid in ("../stdout", "/etc/passwd", "job-id.receipt"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.client.read_log_tail(self.workflow_id, self.attempt_id, invalid)

    def test_log_symlinks_are_rejected_even_when_the_target_is_inside_root(self):
        attempt_dir = self.client.prepare_attempt_directory(self.workflow_id, self.attempt_id)
        target = attempt_dir / "owned.log"
        target.write_text("secret", encoding="utf-8")
        link = attempt_dir / "stdout.log"
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"file symlinks unavailable: {exc}")

        with self.assertRaises(ValueError):
            self.client.read_log_tail(self.workflow_id, self.attempt_id, "stdout")


class CompetitionReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.workflow_root = self.root / "workflow-data"
        self.engine = create_engine(f"sqlite:///{self.root / 'workflow.sqlite'}")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=1000")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        with Session(self.engine) as session:
            owner = User(
                email="stage6-owner@example.com",
                password_hash="hash",
                name="stage6-owner",
                alias="",
                role="operator",
            )
            session.add(owner)
            session.flush()
            run = WorkflowRun(
                id=str(uuid.uuid4()),
                owner_id=owner.id,
                template_version="mos2_v1",
                material="MoS2",
                source_kind="builtin",
                status="validated",
                input_sha256="a" * 64,
                release_commit="b" * 40,
                metadata_json={},
            )
            session.add(run)
            session.flush()
            for position, step_key in enumerate(("relax", "scf", "band", "dos")):
                session.add(
                    WorkflowStep(
                        workflow_id=run.id,
                        step_key=step_key,
                        position=position,
                        status="waiting",
                        parameters_json={},
                    )
                )
            session.add(
                WorkflowEvent(
                    workflow_id=run.id,
                    sequence=1,
                    event_type="workflow_validated",
                    payload_json={"input_sha256": run.input_sha256},
                )
            )
            session.commit()
            self.workflow_id = run.id

        self.script = self.root / "probe.slurm"
        self.script.write_text("#!/bin/bash\n", encoding="utf-8")
        self.executor = RecordingExecutor(stdout=b"41020\n")
        self.slurm = SlurmClient(
            binaries=fixed_binaries(),
            executor=self.executor,
            workflow_root=self.workflow_root,
            allowed_scripts=(self.script,),
        )
        self.reconciler = CompetitionReconciler(
            slurm=self.slurm,
            probe_script=self.script,
        )

    def test_only_one_stale_session_claims_the_first_waiting_step(self):
        first = Session(self.engine, expire_on_commit=False)
        second = Session(self.engine, expire_on_commit=False)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.assertEqual("validated", first.get(WorkflowRun, self.workflow_id).status)
        self.assertEqual("validated", second.get(WorkflowRun, self.workflow_id).status)
        first.commit()
        second.commit()

        claim = self.reconciler.claim_next_attempt(first, self.workflow_id, "success")
        with self.assertRaises(ReconcileError) as denied:
            self.reconciler.claim_next_attempt(second, self.workflow_id, "success")

        self.assertEqual("workflow_not_claimable", denied.exception.code)
        self.assertEqual("relax", claim.submission.step_key)
        self.assertEqual(1, claim.submission.attempt_number)
        self.assertEqual([], self.executor.calls)
        with Session(self.engine) as session:
            attempts = session.scalars(select(WorkflowAttempt)).all()
            self.assertEqual(1, len(attempts))
            self.assertEqual(claim.attempt_id, attempts[0].id)
            self.assertEqual("submitting", attempts[0].status)
            self.assertIsNone(attempts[0].slurm_job_id)
            self.assertEqual(str(claim.submission.attempt_directory), attempts[0].working_directory)
            steps = session.scalars(
                select(WorkflowStep)
                .where(WorkflowStep.workflow_id == self.workflow_id)
                .order_by(WorkflowStep.position)
            ).all()
            self.assertEqual(["submitting", "waiting", "waiting", "waiting"], [step.status for step in steps])
            self.assertEqual("submitting", session.get(WorkflowRun, self.workflow_id).status)
            self.assertEqual(
                1,
                session.scalar(select(func.count()).select_from(WorkflowAttempt)),
            )

    def test_attempt_ledger_is_committed_before_sbatch_and_acceptance_is_atomic(self):
        observed_before_sbatch = []

        class LedgerCheckingExecutor:
            def __call__(inner_self, argv, **kwargs):
                with Session(self.engine) as audit:
                    attempt = audit.scalar(select(WorkflowAttempt))
                    observed_before_sbatch.append(
                        (attempt.status, attempt.slurm_job_id, Path(attempt.working_directory).is_dir())
                    )
                return subprocess.CompletedProcess(argv, 0, b"41020\n", b"")

        slurm = SlurmClient(
            binaries=fixed_binaries(),
            executor=LedgerCheckingExecutor(),
            workflow_root=self.workflow_root,
            allowed_scripts=(self.script,),
        )
        reconciler = CompetitionReconciler(slurm=slurm, probe_script=self.script)

        with Session(self.engine) as session:
            outcome = reconciler.submit_probe(session, self.workflow_id, "success")

        self.assertEqual([("submitting", None, True)], observed_before_sbatch)
        self.assertEqual("queued", outcome.status)
        self.assertEqual("41020", outcome.job_id)
        receipt = self.workflow_root / self.workflow_id / "attempts" / outcome.attempt_id / "job-id.receipt"
        self.assertEqual("41020\n", receipt.read_text(encoding="ascii"))
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, outcome.attempt_id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            self.assertEqual(("queued", "41020"), (attempt.status, attempt.slurm_job_id))
            self.assertEqual("queued", step.status)
            self.assertEqual("queued", run.status)
            events = session.scalars(
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_id == self.workflow_id)
                .order_by(WorkflowEvent.sequence)
            ).all()
            self.assertEqual([1, 2], [event_row.sequence for event_row in events])
            self.assertEqual(["workflow_validated", "submission_accepted"], [row.event_type for row in events])

    def test_scheduler_rejection_is_recorded_without_a_job_receipt(self):
        failing = RecordingExecutor(stderr=b"private scheduler detail", returncode=1)
        slurm = SlurmClient(
            binaries=fixed_binaries(),
            executor=failing,
            workflow_root=self.workflow_root,
            allowed_scripts=(self.script,),
        )
        reconciler = CompetitionReconciler(slurm=slurm, probe_script=self.script)

        with Session(self.engine) as session:
            with self.assertRaises(ReconcileError) as raised:
                reconciler.submit_probe(session, self.workflow_id, "fail")

        self.assertEqual("submission_failed", raised.exception.code)
        self.assertNotIn("private scheduler detail", str(raised.exception))
        with Session(self.engine) as session:
            attempt = session.scalar(select(WorkflowAttempt))
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            self.assertEqual("submission_failed", attempt.status)
            self.assertIsNone(attempt.slurm_job_id)
            self.assertEqual("failed", step.status)
            self.assertEqual("failed", run.status)
            event_row = session.scalar(
                select(WorkflowEvent).where(WorkflowEvent.event_type == "submission_failed")
            )
            self.assertIsNotNone(event_row)
            self.assertEqual("scheduler_rejected", json.loads(event_row.payload_json)["reason_code"])
        self.assertEqual([], list(self.workflow_root.rglob("job-id.receipt")))

    def test_database_failure_after_scheduler_acceptance_recovers_from_exact_receipt(self):
        with Session(self.engine) as session:
            original_commit = session.commit
            commit_calls = 0

            def fail_second_commit():
                nonlocal commit_calls
                commit_calls += 1
                if commit_calls == 2:
                    raise RuntimeError("database finalize failed")
                return original_commit()

            with mock.patch.object(session, "commit", side_effect=fail_second_commit):
                with self.assertRaises(ReconcileError) as raised:
                    self.reconciler.submit_probe(session, self.workflow_id, "success")

        self.assertEqual("submission_uncertain", raised.exception.code)
        self.assertNotIn("database finalize failed", str(raised.exception))
        with Session(self.engine) as session:
            attempt = session.scalar(select(WorkflowAttempt))
            self.assertEqual("submitting", attempt.status)
            self.assertIsNone(attempt.slurm_job_id)
            receipt = Path(attempt.working_directory) / "job-id.receipt"
            self.assertEqual("41020\n", receipt.read_text(encoding="ascii"))
            metadata = json.loads(attempt.metadata_json)
            payload = {
                "jobs": [
                    {
                        "job_id": 41020,
                        "name": metadata["job_name"],
                        "job_state": ["RUNNING"],
                        "exit_code": {
                            "return_code": {"number": 0},
                            "signal": {"id": {"number": 0}},
                        },
                        "state_reason": "None",
                        "current_working_directory": attempt.working_directory,
                        "comment": metadata["comment"],
                        "user_name": "pb23030683",
                        "nodes": "anode02",
                    }
                ]
            }
            event_types = session.scalars(
                select(WorkflowEvent.event_type)
                .where(WorkflowEvent.workflow_id == self.workflow_id)
                .order_by(WorkflowEvent.sequence)
            ).all()
            self.assertEqual(["workflow_validated", "submission_uncertain"], event_types)

        recovery_slurm = SlurmClient(
            binaries=fixed_binaries(),
            executor=SequenceExecutor(response(stdout=json.dumps(payload).encode())),
            workflow_root=self.workflow_root,
            allowed_scripts=(self.script,),
        )
        recovery = CompetitionReconciler(slurm=recovery_slurm, probe_script=self.script)
        with Session(self.engine) as session:
            outcome = recovery.recover_submission(session, attempt.id)

        self.assertEqual(("41020", "queued"), (outcome.job_id, outcome.status))
        with Session(self.engine) as session:
            recovered = session.get(WorkflowAttempt, attempt.id)
            self.assertEqual(("queued", "41020"), (recovered.status, recovered.slurm_job_id))
            event_types = session.scalars(
                select(WorkflowEvent.event_type)
                .where(WorkflowEvent.workflow_id == self.workflow_id)
                .order_by(WorkflowEvent.sequence)
            ).all()
            self.assertEqual(
                ["workflow_validated", "submission_uncertain", "submission_recovered"],
                event_types,
            )

    def test_accepted_workflow_cannot_submit_a_duplicate_job(self):
        with Session(self.engine) as session:
            first = self.reconciler.submit_probe(session, self.workflow_id, "success")
            with self.assertRaises(ReconcileError) as raised:
                self.reconciler.submit_probe(session, self.workflow_id, "success")

        self.assertEqual("workflow_not_claimable", raised.exception.code)
        self.assertEqual("41020", first.job_id)
        self.assertEqual(1, len(self.executor.calls))
        with Session(self.engine) as session:
            self.assertEqual(
                1,
                session.scalar(select(func.count()).select_from(WorkflowAttempt)),
            )


class SlurmObservationTests(unittest.TestCase):
    observed_at = datetime(2026, 8, 15, 9, 30, tzinfo=timezone.utc)

    def client(self, executor: SequenceExecutor) -> SlurmClient:
        return SlurmClient(
            binaries=fixed_binaries(),
            executor=executor,
            clock=lambda: self.observed_at,
        )

    def test_running_job_uses_structured_squeue_fields(self):
        executor = SequenceExecutor(response(stdout=fixture("squeue-running.json")))
        observation = self.client(executor).observe("41001")

        self.assertEqual("41001", observation.job_id)
        self.assertEqual("RUNNING", observation.raw_state)
        self.assertEqual("running", observation.state)
        self.assertEqual("0:0", observation.exit_code)
        self.assertEqual("None", observation.reason)
        self.assertEqual("squeue", observation.source)
        self.assertEqual("lmatelab-12345678-relax-a1", observation.job_name)
        self.assertEqual(
            "/home/scc/pb23030683/lmatelab-107cup/data/workflows/12345678-1234-1234-1234-123456789012/attempts/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            observation.working_directory,
        )
        self.assertEqual(
            "lmatelab:workflow=12345678-1234-1234-1234-123456789012;attempt=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            observation.comment,
        )
        self.assertEqual("pb23030683", observation.user_name)
        self.assertEqual("anode02", observation.node_list)
        self.assertEqual(self.observed_at, observation.observed_at)
        self.assertFalse(observation.stale)
        self.assertEqual(
            ["/usr/bin/squeue", "--json", "--jobs=41001"],
            executor.calls[0][0],
        )

    def test_completed_job_falls_back_to_retained_scontrol_record(self):
        executor = SequenceExecutor(
            response(stdout=json.dumps({"jobs": []}).encode()),
            response(stdout=fixture("scontrol-completed.json")),
        )
        observation = self.client(executor).observe("41002")

        self.assertEqual("COMPLETED", observation.raw_state)
        self.assertEqual("succeeded", observation.state)
        self.assertEqual("0:0", observation.exit_code)
        self.assertEqual("scontrol", observation.source)
        self.assertIsNotNone(observation.finished_at)
        self.assertEqual(
            ["/usr/bin/scontrol", "--json", "show", "job", "41002"],
            executor.calls[1][0],
        )

    def test_live_queue_records_cover_queued_completing_and_unknown_states(self):
        cases = (
            ("PENDING", "queued", None),
            ("COMPLETING", "running", None),
            ("FUTURE_STATE", "unknown", "scheduler_state_unknown"),
        )
        for raw_state, expected, error_code in cases:
            with self.subTest(raw_state=raw_state):
                payload = json.loads(fixture("squeue-running.json"))
                payload["jobs"][0]["job_state"] = [raw_state]
                executor = SequenceExecutor(response(stdout=json.dumps(payload).encode()))

                observation = self.client(executor).observe("41001")

                self.assertEqual(expected, observation.state)
                self.assertEqual(raw_state, observation.raw_state)
                self.assertEqual(error_code, observation.error_code)
                self.assertFalse(observation.stale)

    def test_scontrol_retains_failed_state_and_nonzero_exit_code(self):
        payload = json.loads(fixture("scontrol-completed.json"))
        payload["jobs"][0]["job_state"] = ["FAILED"]
        payload["jobs"][0]["exit_code"]["return_code"]["number"] = 2
        executor = SequenceExecutor(
            response(stdout=json.dumps({"jobs": []}).encode()),
            response(stdout=json.dumps(payload).encode()),
        )

        observation = self.client(executor).observe("41002")

        self.assertEqual("failed", observation.state)
        self.assertEqual("FAILED", observation.raw_state)
        self.assertEqual("2:0", observation.exit_code)
        self.assertEqual("scontrol", observation.source)

    def test_sacct_nested_state_is_used_after_live_records_disappear(self):
        executor = SequenceExecutor(
            response(stdout=json.dumps({"jobs": []}).encode()),
            response(stderr=b"invalid job id", returncode=1),
            response(stdout=fixture("sacct-cancelled.json")),
        )

        observation = self.client(executor).observe("41004")

        self.assertEqual("cancelled", observation.state)
        self.assertEqual("CANCELLED", observation.raw_state)
        self.assertEqual("0:15", observation.exit_code)
        self.assertEqual("operator_cancelled", observation.reason)
        self.assertEqual("sacct", observation.source)
        self.assertEqual("pb23030683", observation.user_name)
        self.assertIsNotNone(observation.finished_at)

    def test_malformed_json_returns_only_a_hash_and_sanitized_error(self):
        malformed = b'{"jobs": [secret-path'
        executor = SequenceExecutor(
            response(stdout=malformed),
            response(stderr=b"invalid job id", returncode=1),
            response(stderr=b"accounting unavailable", returncode=1),
        )

        observation = self.client(executor).observe("41005")

        self.assertEqual("unknown", observation.state)
        self.assertEqual("scheduler_payload_invalid", observation.error_code)
        self.assertEqual(hashlib.sha256(malformed).hexdigest(), observation.payload_sha256)
        self.assertNotIn("secret-path", repr(observation))

    def test_terminal_states_and_exit_codes_are_not_collapsed(self):
        cases = (
            ("PENDING", "0:0", "queued"),
            ("CONFIGURING", "0:0", "queued"),
            ("RUNNING", "0:0", "running"),
            ("COMPLETING", "0:0", "running"),
            ("COMPLETED", "0:0", "succeeded"),
            ("COMPLETED", "2:0", "failed"),
            ("FAILED", "1:0", "failed"),
            ("OUT_OF_MEMORY", "0:9", "failed"),
            ("TIMEOUT", "0:15", "failed"),
            ("CANCELLED", "0:15", "cancelled"),
            ("PREEMPTED", "0:15", "failed"),
            ("FUTURE_STATE", "0:0", "unknown"),
        )
        for raw_state, exit_code, expected in cases:
            with self.subTest(raw_state=raw_state, exit_code=exit_code):
                self.assertEqual(expected, SlurmClient.map_state(raw_state, exit_code))

    def test_unavailable_accounting_fails_closed_to_unknown_stale(self):
        executor = SequenceExecutor(
            response(stdout=json.dumps({"jobs": []}).encode()),
            response(stderr=b"slurm_load_jobs error: Invalid job id specified", returncode=1),
            response(stderr=b"Problem talking to the database: Connection refused", returncode=1),
        )
        observation = self.client(executor).observe("41003")

        self.assertEqual("unknown", observation.state)
        self.assertIsNone(observation.raw_state)
        self.assertEqual("unavailable", observation.source)
        self.assertTrue(observation.stale)
        self.assertEqual("scheduler_record_unavailable", observation.error_code)
        self.assertIsNone(observation.payload_sha256)
        self.assertNotIn("Connection refused", repr(observation))

    def test_job_id_is_validated_before_any_command_runs(self):
        for job_id in ("", "0", "-1", "41001.batch", "41001; scancel 1", " 41001"):
            with self.subTest(job_id=job_id):
                executor = SequenceExecutor()
                with self.assertRaises(ValueError):
                    self.client(executor).observe(job_id)
                self.assertEqual([], executor.calls)


if __name__ == "__main__":
    unittest.main()
