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
