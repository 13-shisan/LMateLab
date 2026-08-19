from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
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
from models_workflow import (
    WorkflowAttempt,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
    canonical_json,
)
import services.competition_slurm as competition_slurm
from services.competition_reconcile import CompetitionReconciler, ReconcileError
from services.competition_slurm import (
    SlurmBinaries,
    SlurmClient,
    SlurmCommandError,
    SlurmCommandTimeout,
    SlurmOutputTooLarge,
    SlurmSubmission,
)

try:
    import fcntl
except ImportError:
    fcntl = None


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


def _install_windows_snapshot_test_patch(test_case: unittest.TestCase) -> None:
    # Windows has no authoritative Slurm path; this supports fake executors only.
    test_case.production_snapshot_creator = (
        competition_slurm._create_private_snapshot_descriptor
    )
    if os.name != "nt":
        return

    def create_test_snapshot_descriptor():
        with tempfile.TemporaryFile(mode="w+b") as handle:
            return os.dup(handle.fileno())

    patcher = mock.patch.object(
        competition_slurm,
        "_create_private_snapshot_descriptor",
        side_effect=create_test_snapshot_descriptor,
    )
    patcher.start()
    test_case.addCleanup(patcher.stop)


class SlurmCommandContractTests(unittest.TestCase):
    def setUp(self):
        _install_windows_snapshot_test_patch(self)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.script = self.root / "probe.slurm"
        self.script.write_text("#!/bin/bash\n", encoding="utf-8")
        self.workflow_id = str(uuid.uuid4())
        self.attempt_id = str(uuid.uuid4())
        self.attempt_dir = self.root / "workflows" / self.workflow_id / "attempts" / self.attempt_id
        self.attempt_dir.mkdir(parents=True)

    def submission(
        self,
        *,
        runner_kind: str = "probe",
        runner_mode: str = "success",
    ) -> SlurmSubmission:
        return SlurmSubmission(
            workflow_id=self.workflow_id,
            attempt_id=self.attempt_id,
            step_key="relax",
            attempt_number=1,
            attempt_directory=self.attempt_dir,
            script_path=self.script,
            runner_kind=runner_kind,
            runner_mode=runner_mode,
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
        submission = self.submission()

        result = client.test_submission(submission)

        self.assertEqual("sbatch: Job 123 to start later", result.stdout)
        self.assertEqual(1, len(executor.calls))
        argv, kwargs = executor.calls[0]
        self.assertEqual("/usr/bin/sbatch", argv[0])
        self.assertEqual("--test-only", argv[1])
        self.assertIn("--parsable", argv)
        self.assertIn(f"--chdir={self.attempt_dir}", argv)
        self.assertIn(f"--output={self.attempt_dir / 'stdout.log'}", argv)
        self.assertIn(f"--error={self.attempt_dir / 'stderr.log'}", argv)
        self.assertIn(f"--comment={submission.comment}", argv)
        self.assertIn("--job-name=lmatelab-", " ".join(argv))
        self.assertEqual(
            ["success", self.workflow_id, self.attempt_id],
            argv[-3:],
        )
        pass_fds = kwargs.get("pass_fds", ())
        self.assertEqual(1, len(pass_fds))
        self.assertEqual(f"/proc/self/fd/{pass_fds[0]}", argv[-4])
        self.assertIs(False, kwargs["shell"])
        self.assertIs(False, kwargs["check"])
        self.assertEqual(subprocess.PIPE, kwargs["stdout"])
        self.assertEqual(subprocess.PIPE, kwargs["stderr"])
        self.assertEqual(3.0, kwargs["timeout"])
        with self.assertRaises(OSError):
            os.fstat(pass_fds[0])

    def test_submission_accepts_only_fixed_runner_mode_pairs(self):
        probe = self.submission(runner_kind="probe", runner_mode="success")
        vasp = self.submission(runner_kind="vasp", runner_mode="scf")

        self.assertEqual(("probe", "success"), (probe.runner_kind, probe.runner_mode))
        self.assertEqual(("vasp", "scf"), (vasp.runner_kind, vasp.runner_mode))
        for kind, mode in (("probe", "scf"), ("vasp", "success"), ("shell", "id")):
            with self.subTest(kind=kind, mode=mode), self.assertRaises(ValueError):
                self.submission(runner_kind=kind, runner_mode=mode)

    def test_submission_identity_binds_runner_mode_and_script_digest(self):
        submission = self.submission()
        expected_sha256 = hashlib.sha256(self.script.read_bytes()).hexdigest()

        self.assertEqual(expected_sha256, submission.script_sha256)
        self.assertEqual(
            (
                f"lmatelab:workflow={self.workflow_id};attempt={self.attempt_id};"
                f"runner=probe;mode=success;script_sha256={expected_sha256}"
            ),
            submission.comment,
        )
        self.assertLessEqual(len(submission.comment.encode("utf-8")), 256)

    def test_submit_rejects_script_changed_after_submission_construction(self):
        executor = RecordingExecutor(stdout=b"12345\n")
        client = self.client(executor)
        submission = self.submission()
        self.script.write_text("#!/bin/bash\necho changed\n", encoding="utf-8")

        with self.assertRaises(ValueError):
            client.submit(submission)

        self.assertEqual([], executor.calls)

    def test_submit_consumes_pinned_descriptor_when_source_path_is_replaced(self):
        original = self.script.read_bytes()
        replacement = b"#!/bin/bash\necho replaced\n"

        class ReplacingExecutor:
            def __init__(inner_self):
                inner_self.calls = []
                inner_self.consumed = None
                inner_self.emulated_windows_replace = False

            def __call__(inner_self, argv, **kwargs):
                inner_self.calls.append((list(argv), dict(kwargs)))
                replacement_path = self.script.with_suffix(".replacement")
                replacement_path.write_bytes(replacement)
                try:
                    os.replace(replacement_path, self.script)
                except PermissionError:
                    inner_self.emulated_windows_replace = True
                    replacement_path.unlink()

                script_argument = argv[-4]
                if script_argument.startswith("/proc/self/fd/"):
                    descriptor = int(script_argument.rsplit("/", 1)[1])
                    duplicate = os.dup(descriptor)
                    try:
                        os.lseek(duplicate, 0, os.SEEK_SET)
                        chunks = []
                        while chunk := os.read(duplicate, 64 * 1024):
                            chunks.append(chunk)
                        inner_self.consumed = b"".join(chunks)
                    finally:
                        os.close(duplicate)
                else:
                    inner_self.consumed = (
                        replacement
                        if inner_self.emulated_windows_replace
                        else Path(script_argument).read_bytes()
                    )
                return subprocess.CompletedProcess(argv, 0, b"12345\n", b"")

        executor = ReplacingExecutor()
        client = self.client(executor)
        submission = self.submission()

        self.assertEqual("12345", client.submit(submission))

        self.assertEqual(original, executor.consumed)
        argv, kwargs = executor.calls[0]
        pass_fds = kwargs.get("pass_fds", ())
        self.assertEqual(1, len(pass_fds))
        self.assertEqual(f"/proc/self/fd/{pass_fds[0]}", argv[-4])
        self.assertIs(False, kwargs["shell"])
        with self.assertRaises(OSError):
            os.fstat(pass_fds[0])

    def test_submit_consumes_immutable_snapshot_when_source_is_modified_in_place(self):
        original = self.script.read_bytes()
        replacement = b"#!/bin/bash\necho modified in place\n"

        class InPlaceMutationExecutor:
            def __init__(inner_self):
                inner_self.calls = []
                inner_self.consumed = None

            def __call__(inner_self, argv, **kwargs):
                inner_self.calls.append((list(argv), dict(kwargs)))
                with self.script.open("r+b") as handle:
                    handle.seek(0)
                    handle.truncate(0)
                    handle.write(replacement)
                    handle.flush()

                descriptor = kwargs["pass_fds"][0]
                duplicate = os.dup(descriptor)
                try:
                    os.lseek(duplicate, 0, os.SEEK_SET)
                    chunks = []
                    while chunk := os.read(duplicate, 64 * 1024):
                        chunks.append(chunk)
                    inner_self.consumed = b"".join(chunks)
                finally:
                    os.close(duplicate)
                return subprocess.CompletedProcess(argv, 0, b"12345\n", b"")

        executor = InPlaceMutationExecutor()
        submission = self.submission()

        self.assertEqual("12345", self.client(executor).submit(submission))

        self.assertEqual(original, executor.consumed)
        argv, kwargs = executor.calls[0]
        self.assertIn(f"--comment={submission.comment}", argv)
        self.assertEqual(f"/proc/self/fd/{kwargs['pass_fds'][0]}", argv[-4])
        with self.assertRaises(OSError):
            os.fstat(kwargs["pass_fds"][0])

    def test_linux_snapshot_requests_and_verifies_all_required_seals(self):
        allow_sealing = 0x0002
        close_on_exec = 0x0001

        class FakeFcntl:
            F_ADD_SEALS = 1033
            F_GET_SEALS = 1034
            F_SEAL_SEAL = 0x0001
            F_SEAL_SHRINK = 0x0002
            F_SEAL_GROW = 0x0004
            F_SEAL_WRITE = 0x0008

            def __init__(inner_self):
                inner_self.calls = []
                inner_self.applied = 0

            def fcntl(inner_self, descriptor, operation, argument=0):
                inner_self.calls.append((descriptor, operation, argument))
                if operation == inner_self.F_ADD_SEALS:
                    inner_self.applied = argument
                    return 0
                if operation == inner_self.F_GET_SEALS:
                    return inner_self.applied
                raise AssertionError(f"unexpected fcntl operation: {operation}")

        fake_fcntl = FakeFcntl()
        memfd_calls = []
        snapshot_path = self.root / "fake-memfd"

        def fake_memfd_create(name, flags):
            memfd_calls.append((name, flags))
            return os.open(
                snapshot_path,
                os.O_RDWR | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0),
                0o600,
            )

        submission = self.submission()
        executor = RecordingExecutor(stdout=b"12345\n")
        with (
            mock.patch.object(competition_slurm, "_IS_LINUX", True, create=True),
            mock.patch.object(
                competition_slurm,
                "_create_private_snapshot_descriptor",
                new=self.production_snapshot_creator,
            ),
            mock.patch.object(competition_slurm, "_fcntl", fake_fcntl, create=True),
            mock.patch.object(
                competition_slurm.os,
                "memfd_create",
                side_effect=fake_memfd_create,
                create=True,
            ),
            mock.patch.object(
                competition_slurm.os,
                "MFD_ALLOW_SEALING",
                allow_sealing,
                create=True,
            ),
            mock.patch.object(
                competition_slurm.os,
                "MFD_CLOEXEC",
                close_on_exec,
                create=True,
            ),
        ):
            self.assertEqual("12345", self.client(executor).submit(submission))

        required_seals = (
            fake_fcntl.F_SEAL_WRITE
            | fake_fcntl.F_SEAL_GROW
            | fake_fcntl.F_SEAL_SHRINK
            | fake_fcntl.F_SEAL_SEAL
        )
        self.assertEqual(1, len(memfd_calls))
        self.assertEqual(allow_sealing | close_on_exec, memfd_calls[0][1])
        self.assertEqual(
            [
                mock.call(
                    mock.ANY,
                    fake_fcntl.F_ADD_SEALS,
                    required_seals,
                ),
                mock.call(mock.ANY, fake_fcntl.F_GET_SEALS, 0),
            ],
            [mock.call(*call) for call in fake_fcntl.calls],
        )

    def test_linux_submission_fails_closed_and_closes_fds_when_seals_are_unverified(self):
        class UnverifiedFcntl:
            F_ADD_SEALS = 1033
            F_GET_SEALS = 1034
            F_SEAL_SEAL = 0x0001
            F_SEAL_SHRINK = 0x0002
            F_SEAL_GROW = 0x0004
            F_SEAL_WRITE = 0x0008

            @staticmethod
            def fcntl(descriptor, operation, argument=0):
                if operation == UnverifiedFcntl.F_ADD_SEALS:
                    return 0
                if operation == UnverifiedFcntl.F_GET_SEALS:
                    return 0
                raise AssertionError(f"unexpected fcntl operation: {operation}")

        snapshot_descriptors = []
        source_descriptors = []
        snapshot_path = self.root / "unsealed-memfd"
        real_open_hashed_script = competition_slurm._open_hashed_script

        def fake_memfd_create(name, flags):
            descriptor = os.open(
                snapshot_path,
                os.O_RDWR | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0),
                0o600,
            )
            snapshot_descriptors.append(descriptor)
            return descriptor

        def recording_open_hashed_script(path):
            descriptor, digest = real_open_hashed_script(path)
            source_descriptors.append(descriptor)
            return descriptor, digest

        submission = self.submission()
        executor = RecordingExecutor(stdout=b"12345\n")
        with (
            mock.patch.object(competition_slurm, "_IS_LINUX", True, create=True),
            mock.patch.object(
                competition_slurm,
                "_create_private_snapshot_descriptor",
                new=self.production_snapshot_creator,
            ),
            mock.patch.object(competition_slurm, "_fcntl", UnverifiedFcntl(), create=True),
            mock.patch.object(
                competition_slurm,
                "_open_hashed_script",
                side_effect=recording_open_hashed_script,
            ),
            mock.patch.object(
                competition_slurm.os,
                "memfd_create",
                side_effect=fake_memfd_create,
                create=True,
            ),
            mock.patch.object(
                competition_slurm.os,
                "MFD_ALLOW_SEALING",
                0x0002,
                create=True,
            ),
            mock.patch.object(
                competition_slurm.os,
                "MFD_CLOEXEC",
                0x0001,
                create=True,
            ),
        ):
            with self.assertRaises(ValueError):
                self.client(executor).submit(submission)

        self.assertEqual([], executor.calls)
        self.assertEqual(1, len(snapshot_descriptors))
        self.assertEqual(1, len(source_descriptors))
        for descriptor in snapshot_descriptors + source_descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_linux_submission_rejects_snapshot_modified_before_sealing(self):
        replacement = b"#!/bin/bash\necho pre-seal mutation\n"

        class MutatingFcntl:
            F_ADD_SEALS = 1033
            F_GET_SEALS = 1034
            F_SEAL_SEAL = 0x0001
            F_SEAL_SHRINK = 0x0002
            F_SEAL_GROW = 0x0004
            F_SEAL_WRITE = 0x0008

            def __init__(inner_self):
                inner_self.applied = 0

            def fcntl(inner_self, descriptor, operation, argument=0):
                if operation == inner_self.F_ADD_SEALS:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    os.ftruncate(descriptor, 0)
                    os.write(descriptor, replacement)
                    inner_self.applied = argument
                    return 0
                if operation == inner_self.F_GET_SEALS:
                    return inner_self.applied
                raise AssertionError(f"unexpected fcntl operation: {operation}")

        snapshot_descriptors = []
        snapshot_path = self.root / "mutated-memfd"

        def fake_memfd_create(name, flags):
            descriptor = os.open(
                snapshot_path,
                os.O_RDWR | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0),
                0o600,
            )
            snapshot_descriptors.append(descriptor)
            return descriptor

        submission = self.submission()
        executor = RecordingExecutor(stdout=b"12345\n")
        with (
            mock.patch.object(competition_slurm, "_IS_LINUX", True),
            mock.patch.object(
                competition_slurm,
                "_create_private_snapshot_descriptor",
                new=self.production_snapshot_creator,
            ),
            mock.patch.object(competition_slurm, "_fcntl", MutatingFcntl()),
            mock.patch.object(
                competition_slurm.os,
                "memfd_create",
                side_effect=fake_memfd_create,
                create=True,
            ),
            mock.patch.object(
                competition_slurm.os,
                "MFD_ALLOW_SEALING",
                0x0002,
                create=True,
            ),
            mock.patch.object(
                competition_slurm.os,
                "MFD_CLOEXEC",
                0x0001,
                create=True,
            ),
        ):
            with self.assertRaises(ValueError):
                self.client(executor).submit(submission)

        self.assertEqual([], executor.calls)
        self.assertEqual(1, len(snapshot_descriptors))
        with self.assertRaises(OSError):
            os.fstat(snapshot_descriptors[0])

    @unittest.skipUnless(os.name == "nt", "Windows local-test fallback only")
    def test_windows_snapshot_fallback_is_rejected_for_the_default_executor(self):
        submission = self.submission()
        client = SlurmClient(
            binaries=fixed_binaries(),
            executor=subprocess.run,
            timeout_seconds=3.0,
            allowed_scripts=(self.script,),
            workflow_root=self.root / "workflows",
        )
        recorder = RecordingExecutor(stdout=b"12345\n")
        client._executor = recorder

        with (
            mock.patch.object(
                competition_slurm,
                "_create_private_snapshot_descriptor",
                new=self.production_snapshot_creator,
            ),
            self.assertRaises(ValueError),
        ):
            client.submit(submission)

        self.assertEqual([], recorder.calls)

    @unittest.skipUnless(os.name == "nt", "Windows submissions are unsupported")
    def test_windows_submission_fails_closed_for_an_executor_wrapper(self):
        recorder = RecordingExecutor(stdout=b"12345\n")

        def wrapped_executor(argv, **kwargs):
            return recorder(argv, **kwargs)

        client = self.client(wrapped_executor)

        with (
            mock.patch.object(
                competition_slurm,
                "_create_private_snapshot_descriptor",
                new=self.production_snapshot_creator,
            ),
            self.assertRaises(ValueError),
        ):
            client.submit(self.submission())

        self.assertEqual([], recorder.calls)

    @unittest.skipUnless(
        sys.platform.startswith("linux")
        and hasattr(os, "memfd_create")
        and fcntl is not None
        and hasattr(fcntl, "F_ADD_SEALS"),
        "Linux memfd sealing is required",
    )
    def test_inherited_linux_snapshot_is_sealed_against_write_and_truncate(self):
        original = self.script.read_bytes()
        test_case = self

        class SealInspectingExecutor:
            def __init__(inner_self):
                inner_self.calls = []
                inner_self.consumed = None

            def __call__(inner_self, argv, **kwargs):
                inner_self.calls.append((list(argv), dict(kwargs)))
                descriptor = kwargs["pass_fds"][0]
                required_seals = (
                    fcntl.F_SEAL_WRITE
                    | fcntl.F_SEAL_GROW
                    | fcntl.F_SEAL_SHRINK
                    | fcntl.F_SEAL_SEAL
                )
                try:
                    applied_seals = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
                except OSError:
                    applied_seals = 0
                test_case.assertEqual(required_seals, applied_seals & required_seals)
                with test_case.assertRaises(OSError):
                    os.write(descriptor, b"changed")
                with test_case.assertRaises(OSError):
                    os.ftruncate(descriptor, 0)

                duplicate = os.dup(descriptor)
                try:
                    os.lseek(duplicate, 0, os.SEEK_SET)
                    inner_self.consumed = os.read(duplicate, 64 * 1024)
                finally:
                    os.close(duplicate)
                return subprocess.CompletedProcess(argv, 0, b"12345\n", b"")

        executor = SealInspectingExecutor()

        self.assertEqual("12345", self.client(executor).submit(self.submission()))

        self.assertEqual(original, executor.consumed)
        inherited_descriptor = executor.calls[0][1]["pass_fds"][0]
        with self.assertRaises(OSError):
            os.fstat(inherited_descriptor)

    def test_submission_descriptor_closes_after_command_error(self):
        executor = RecordingExecutor(stderr=b"private scheduler detail", returncode=1)
        client = self.client(executor)

        with self.assertRaises(SlurmCommandError):
            client.submit(self.submission())

        pass_fds = executor.calls[0][1].get("pass_fds", ())
        self.assertEqual(1, len(pass_fds))
        with self.assertRaises(OSError):
            os.fstat(pass_fds[0])

    def test_submission_descriptor_closes_after_timeout(self):
        class TimeoutExecutor:
            def __init__(inner_self):
                inner_self.calls = []

            def __call__(inner_self, argv, **kwargs):
                inner_self.calls.append((list(argv), dict(kwargs)))
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        executor = TimeoutExecutor()
        client = self.client(executor)

        with self.assertRaises(SlurmCommandTimeout):
            client.submit(self.submission())

        pass_fds = executor.calls[0][1].get("pass_fds", ())
        self.assertEqual(1, len(pass_fds))
        with self.assertRaises(OSError):
            os.fstat(pass_fds[0])

    def test_source_descriptor_closes_when_initial_hash_is_interrupted(self):
        opened_descriptors = []
        real_os_open = competition_slurm.os.open

        def recording_os_open(*args, **kwargs):
            descriptor = real_os_open(*args, **kwargs)
            opened_descriptors.append(descriptor)
            return descriptor

        with (
            mock.patch.object(
                competition_slurm.os,
                "open",
                side_effect=recording_os_open,
            ),
            mock.patch.object(
                competition_slurm,
                "_hash_script_descriptor",
                side_effect=KeyboardInterrupt,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            competition_slurm._open_hashed_script(self.script)

        self.assertEqual(1, len(opened_descriptors))
        descriptor_closed = False
        try:
            os.fstat(opened_descriptors[0])
        except OSError:
            descriptor_closed = True
        finally:
            if not descriptor_closed:
                os.close(opened_descriptors[0])
        self.assertTrue(descriptor_closed)

    def test_source_and_snapshot_descriptors_close_when_copy_is_interrupted(self):
        source_descriptors = []
        snapshot_descriptors = []
        real_open_hashed_script = competition_slurm._open_hashed_script
        snapshot_path = self.root / "interrupted-snapshot"

        def recording_open_hashed_script(path):
            descriptor, digest = real_open_hashed_script(path)
            source_descriptors.append(descriptor)
            return descriptor, digest

        def fake_snapshot_descriptor():
            descriptor = os.open(
                snapshot_path,
                os.O_RDWR | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0),
                0o600,
            )
            snapshot_descriptors.append(descriptor)
            return descriptor

        submission = self.submission()
        executor = RecordingExecutor(stdout=b"12345\n")
        with (
            mock.patch.object(
                competition_slurm,
                "_open_hashed_script",
                side_effect=recording_open_hashed_script,
            ),
            mock.patch.object(
                competition_slurm,
                "_create_private_snapshot_descriptor",
                side_effect=fake_snapshot_descriptor,
            ),
            mock.patch.object(
                competition_slurm,
                "_copy_script_descriptor",
                side_effect=KeyboardInterrupt,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.client(executor).submit(submission)

        self.assertEqual([], executor.calls)
        self.assertEqual(1, len(source_descriptors))
        self.assertEqual(1, len(snapshot_descriptors))
        closed = []
        for descriptor in source_descriptors + snapshot_descriptors:
            try:
                os.fstat(descriptor)
            except OSError:
                closed.append(True)
            else:
                closed.append(False)
                os.close(descriptor)
        self.assertEqual([True, True], closed)

    def test_submission_rejects_a_script_outside_the_allowlist(self):
        foreign_script = self.root / "foreign.slurm"
        foreign_script.write_text("#!/bin/bash\n", encoding="utf-8")
        submission = SlurmSubmission(
            workflow_id=self.workflow_id,
            attempt_id=self.attempt_id,
            step_key="relax",
            attempt_number=1,
            attempt_directory=self.attempt_dir,
            script_path=foreign_script,
            runner_kind="probe",
            runner_mode="success",
        )
        executor = RecordingExecutor(stdout=b"12345\n")

        with self.assertRaises(ValueError):
            self.client(executor).submit(submission)

        self.assertEqual([], executor.calls)

    def test_vasp_submission_argv_is_fixed_and_shell_free(self):
        executor = RecordingExecutor()
        client = self.client(executor)
        submission = self.submission(runner_kind="vasp", runner_mode="dos")

        result = client.test_submission(submission)

        self.assertEqual(0, result.returncode)
        argv = executor.calls[-1][0]
        self.assertEqual(["dos", submission.workflow_id, submission.attempt_id], argv[-3:])
        self.assertNotIn("--wrap", argv)

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
                    runner_kind="probe",
                    runner_mode="success",
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
        _install_windows_snapshot_test_patch(self)
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
                metadata_json={
                    "normalized_payload": {
                        "parameters": {},
                        "source_kind": "builtin",
                        "steps": ["relax", "scf", "band", "dos"],
                        "template_version": "mos2_v1",
                    }
                },
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
        self.vasp_script = self.root / "vasp-stage.slurm"
        self.vasp_script.write_text("#!/bin/bash\n", encoding="utf-8")
        self.executor = RecordingExecutor(stdout=b"41020\n")
        self.slurm = SlurmClient(
            binaries=fixed_binaries(),
            executor=self.executor,
            workflow_root=self.workflow_root,
            allowed_scripts=(self.script, self.vasp_script),
        )
        self.reconciler = CompetitionReconciler(
            slurm=self.slurm,
            probe_script=self.script,
        )

    def accepted_attempt(self):
        with Session(self.engine) as session:
            outcome = self.reconciler.submit_probe(session, self.workflow_id, "success")
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, outcome.attempt_id)
            metadata = json.loads(attempt.metadata_json)
            return outcome, {
                "jobs": [
                    {
                        "job_id": int(outcome.job_id),
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

    def vasp_reconciler(self):
        return CompetitionReconciler(
            slurm=self.slurm,
            probe_script=self.script,
            vasp_script=self.vasp_script,
        )

    def claim_vasp(self, **overrides):
        options = {
            "step_key": "scf",
            "runner_kind": "vasp",
            "runner_mode": "scf",
            "script_path": self.vasp_script,
            "claimable_run_statuses": frozenset({"running"}),
        }
        options.update(overrides)
        with Session(self.engine) as session:
            return self.vasp_reconciler().claim_attempt(
                session,
                self.workflow_id,
                **options,
            )

    def set_run_status(self, status):
        with Session(self.engine) as session:
            session.get(WorkflowRun, self.workflow_id).status = status
            session.commit()

    def test_vasp_claim_targets_only_the_requested_fixed_step(self):
        self.set_run_status("running")

        claim = self.claim_vasp()

        self.assertEqual("scf", claim.submission.step_key)
        self.assertEqual("preparing", claim.status)
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, claim.attempt_id)
            step = session.get(WorkflowStep, claim.step_id)
            metadata = json.loads(attempt.metadata_json)
            self.assertEqual(("preparing", "preparing"), (attempt.status, step.status))
            self.assertEqual("running", session.get(WorkflowRun, self.workflow_id).status)
            self.assertEqual("vasp", metadata["runner_kind"])
            self.assertEqual("scf", metadata["runner_mode"])
            self.assertEqual(str(self.vasp_script.resolve()), metadata["script_path"])
            expected_sha256 = hashlib.sha256(self.vasp_script.read_bytes()).hexdigest()
            self.assertEqual(expected_sha256, metadata.get("script_sha256"))
            self.assertEqual(expected_sha256, claim.submission.script_sha256)
            self.assertEqual(claim.submission.comment, metadata["comment"])

    def test_vasp_claim_persists_only_the_bound_scope_identity(self):
        self.set_run_status("running")

        claim = self.claim_vasp()

        with Session(self.engine) as session:
            run = session.get(WorkflowRun, self.workflow_id)
            attempt = session.get(WorkflowAttempt, claim.attempt_id)
            metadata = json.loads(attempt.metadata_json)
            run_metadata = json.loads(run.metadata_json)
        self.assertEqual(
            hashlib.sha256(
                canonical_json(
                    {
                        "version": 1,
                        "template_version": "mos2_v1",
                        "material": "MoS2",
                        "source_kind": "builtin",
                        "input_sha256": "a" * 64,
                        "release_commit": "b" * 40,
                        "metadata": run_metadata,
                    }
                ).encode("utf-8")
            ).hexdigest(),
            metadata.get("execution_scope_v1_sha256"),
        )
        self.assertNotIn("normalized_payload", metadata)

    def test_vasp_promotion_rejects_scope_mutated_after_claim(self):
        self.set_run_status("running")
        claim = self.claim_vasp()
        with Session(self.engine) as session:
            run = session.get(WorkflowRun, self.workflow_id)
            metadata = json.loads(run.metadata_json)
            metadata["normalized_payload"]["source_kind"] = "foreign"
            run.metadata_json = metadata
            session.commit()

        with Session(self.engine) as session, self.assertRaises(ReconcileError) as raised:
            self.vasp_reconciler().promote_claim(
                session,
                claim,
                claimable_run_statuses=frozenset({"running"}),
            )

        self.assertEqual("workflow_scope_changed", raised.exception.code)
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, claim.attempt_id)
            step = session.get(WorkflowStep, claim.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            self.assertEqual(
                ("preparing", "preparing", "running"),
                (attempt.status, step.status, run.status),
            )

    def test_claim_rejects_a_non_fixed_step(self):
        self.set_run_status("running")

        with self.assertRaises(ReconcileError) as raised:
            self.claim_vasp(step_key="postprocess", runner_mode="postprocess")

        self.assertEqual("invalid_step", raised.exception.code)

    def test_claim_rejects_a_runner_mode_that_does_not_match_the_vasp_step(self):
        self.set_run_status("running")

        with self.assertRaises(ReconcileError) as raised:
            self.claim_vasp(runner_mode="dos")

        self.assertEqual("invalid_runner_contract", raised.exception.code)

    def test_claim_rejects_a_probe_runner_outside_the_fixed_stage6_step(self):
        self.set_run_status("running")

        with Session(self.engine) as session, self.assertRaises(ReconcileError) as raised:
            self.reconciler.claim_attempt(
                session,
                self.workflow_id,
                step_key="scf",
                runner_kind="probe",
                runner_mode="success",
                script_path=self.script,
                claimable_run_statuses=frozenset({"running"}),
            )

        self.assertEqual("invalid_runner_contract", raised.exception.code)

    def test_claim_rejects_an_unconfigured_runner_or_script(self):
        self.set_run_status("running")
        foreign_script = self.root / "foreign.slurm"
        foreign_script.write_text("#!/bin/bash\n", encoding="utf-8")

        cases = (
            {"runner_kind": "shell", "runner_mode": "scf"},
            {"script_path": foreign_script},
        )
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ReconcileError) as raised:
                self.claim_vasp(**options)
            self.assertEqual("invalid_runner_contract", raised.exception.code)

    def test_claim_rejects_a_step_that_is_not_waiting(self):
        self.set_run_status("running")
        with Session(self.engine) as session:
            step = session.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_id == self.workflow_id,
                    WorkflowStep.step_key == "scf",
                )
            )
            step.status = "succeeded"
            session.commit()

        with self.assertRaises(ReconcileError) as raised:
            self.claim_vasp()

        self.assertEqual("workflow_step_not_claimable", raised.exception.code)
        with Session(self.engine) as session:
            self.assertEqual(0, session.scalar(select(func.count()).select_from(WorkflowAttempt)))

    def test_claim_rejects_an_unmet_run_status(self):
        with self.assertRaises(ReconcileError) as raised:
            self.claim_vasp()

        self.assertEqual("workflow_not_claimable", raised.exception.code)
        with Session(self.engine) as session:
            scf = session.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_id == self.workflow_id,
                    WorkflowStep.step_key == "scf",
                )
            )
            self.assertEqual("waiting", scf.status)
            self.assertEqual(0, session.scalar(select(func.count()).select_from(WorkflowAttempt)))

    def test_only_one_stale_session_claims_the_requested_step(self):
        self.set_run_status("running")
        first = Session(self.engine, expire_on_commit=False)
        second = Session(self.engine, expire_on_commit=False)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        for session in (first, second):
            self.assertEqual("running", session.get(WorkflowRun, self.workflow_id).status)
            session.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_id == self.workflow_id,
                    WorkflowStep.step_key == "scf",
                )
            )
            session.commit()

        options = {
            "step_key": "scf",
            "runner_kind": "vasp",
            "runner_mode": "scf",
            "script_path": self.vasp_script,
            "claimable_run_statuses": frozenset({"running"}),
        }
        reconciler = self.vasp_reconciler()
        claim = reconciler.claim_attempt(first, self.workflow_id, **options)
        with self.assertRaises(ReconcileError) as denied:
            reconciler.claim_attempt(second, self.workflow_id, **options)

        self.assertEqual("workflow_has_active_attempt", denied.exception.code)
        self.assertEqual("scf", claim.submission.step_key)
        with Session(self.engine) as session:
            attempts = session.scalars(select(WorkflowAttempt)).all()
            self.assertEqual(1, len(attempts))
            self.assertEqual("preparing", attempts[0].status)

    def test_claim_rejects_every_other_active_attempt_status(self):
        self.set_run_status("running")
        active_statuses = (
            "preparing",
            "submitting",
            "queued",
            "running",
            "awaiting_acceptance",
            "cancelling",
        )
        with Session(self.engine) as session:
            relax = session.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_id == self.workflow_id,
                    WorkflowStep.step_key == "relax",
                )
            )

        for attempt_number, active_status in enumerate(active_statuses, start=1):
            with self.subTest(active_status=active_status):
                active_attempt_id = str(uuid.uuid4())
                with Session(self.engine) as session:
                    session.add(
                        WorkflowAttempt(
                            id=active_attempt_id,
                            step_id=relax.id,
                            attempt_number=attempt_number,
                            status=active_status,
                            metadata_json={},
                        )
                    )
                    session.commit()
                try:
                    with self.assertRaises(ReconcileError) as raised:
                        self.claim_vasp()
                    self.assertEqual("workflow_has_active_attempt", raised.exception.code)
                finally:
                    with Session(self.engine) as session:
                        attempt = session.get(WorkflowAttempt, active_attempt_id)
                        if attempt is not None:
                            session.delete(attempt)
                            session.commit()

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

            def fail_finalize_commit():
                nonlocal commit_calls
                commit_calls += 1
                if commit_calls == 3:
                    raise RuntimeError("database finalize failed")
                return original_commit()

            with mock.patch.object(session, "commit", side_effect=fail_finalize_commit):
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

    def test_recovery_rejects_script_changed_at_the_claimed_path(self):
        with Session(self.engine) as session:
            claim = self.reconciler.claim_next_attempt(
                session,
                self.workflow_id,
                "success",
            )
        self.slurm.write_job_receipt(self.workflow_id, claim.attempt_id, "41020")
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, claim.attempt_id)
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

        self.script.write_text("#!/bin/bash\necho changed\n", encoding="utf-8")
        recovery = CompetitionReconciler(
            slurm=SlurmClient(
                binaries=fixed_binaries(),
                executor=SequenceExecutor(response(stdout=json.dumps(payload).encode())),
                workflow_root=self.workflow_root,
                allowed_scripts=(self.script,),
            ),
            probe_script=self.script,
        )
        with Session(self.engine) as session, self.assertRaises(ReconcileError) as raised:
            recovery.recover_submission(session, claim.attempt_id)

        self.assertEqual("submission_not_recoverable", raised.exception.code)

    def _legacy_probe_attempt(
        self,
        *,
        status="queued",
        step_key="relax",
        probe_mode="success",
        metadata_updates=None,
    ):
        attempt_id = str(uuid.uuid4())
        attempt_number = 1
        attempt_directory = self.slurm.prepare_attempt_directory(
            self.workflow_id,
            attempt_id,
        )
        comment = f"lmatelab:workflow={self.workflow_id};attempt={attempt_id}"
        job_name = f"lmatelab-{self.workflow_id[:8]}-{step_key}-a{attempt_number}"
        metadata = {
            "comment": comment,
            "job_name": job_name,
            "probe_mode": probe_mode,
        }
        if metadata_updates:
            metadata.update(metadata_updates)
        job_id = None if status == "submitting" else "51010"
        with Session(self.engine) as session:
            run = session.get(WorkflowRun, self.workflow_id)
            step = session.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_id == self.workflow_id,
                    WorkflowStep.step_key == step_key,
                )
            )
            run.status = status
            step.status = status
            session.add(
                WorkflowAttempt(
                    id=attempt_id,
                    step_id=step.id,
                    attempt_number=attempt_number,
                    status=status,
                    slurm_job_id=job_id,
                    working_directory=str(attempt_directory),
                    metadata_json=metadata,
                )
            )
            session.commit()
        payload = {
            "jobs": [
                {
                    "job_id": 51010,
                    "name": job_name,
                    "job_state": ["RUNNING"],
                    "exit_code": {
                        "return_code": {"number": 0},
                        "signal": {"id": {"number": 0}},
                    },
                    "state_reason": "None",
                    "current_working_directory": str(attempt_directory),
                    "comment": comment,
                    "user_name": "pb23030683",
                    "nodes": "anode02",
                }
            ]
        }
        return attempt_id, payload

    def test_legacy_submitting_probe_recovers_with_historical_identity(self):
        attempt_id, payload = self._legacy_probe_attempt(status="submitting")
        self.slurm.write_job_receipt(self.workflow_id, attempt_id, "51010")
        recovery = CompetitionReconciler(
            slurm=SlurmClient(
                binaries=fixed_binaries(),
                executor=SequenceExecutor(response(stdout=json.dumps(payload).encode())),
                workflow_root=self.workflow_root,
                allowed_scripts=(self.script,),
            ),
            probe_script=self.script,
        )

        try:
            with Session(self.engine) as session:
                result = recovery.recover_submission(session, attempt_id)
        except ReconcileError as exc:
            self.fail(f"legacy submission was rejected with {exc.code}")

        self.assertEqual(("51010", "queued"), (result.job_id, result.status))

    def test_legacy_probe_reconciles_queued_running_and_completed_states(self):
        attempt_id, payload = self._legacy_probe_attempt()
        observed = []
        for raw_state, expected in (
            ("PENDING", "queued"),
            ("RUNNING", "running"),
            ("COMPLETED", "succeeded"),
        ):
            try:
                result = self.reconcile_with_payload(
                    attempt_id,
                    self.payload_with_state(payload, raw_state),
                )
            except ReconcileError as exc:
                self.fail(f"legacy attempt was rejected with {exc.code}")
            observed.append(result.status)

        self.assertEqual(["queued", "running", "succeeded"], observed)

    def test_mixed_or_invalid_legacy_runner_metadata_is_rejected(self):
        cases = (
            {
                "label": "mixed",
                "step_key": "relax",
                "probe_mode": "success",
                "updates": {
                    "runner_kind": "probe",
                    "runner_mode": "success",
                    "script_path": str(self.script.resolve()),
                },
            },
            {
                "label": "invalid-mode",
                "step_key": "relax",
                "probe_mode": "scf",
                "updates": None,
            },
            {
                "label": "non-relax",
                "step_key": "scf",
                "probe_mode": "success",
                "updates": None,
            },
        )
        for case in cases:
            with self.subTest(label=case["label"]):
                attempt_id, payload = self._legacy_probe_attempt(
                    step_key=case["step_key"],
                    probe_mode=case["probe_mode"],
                    metadata_updates=case["updates"],
                )
                try:
                    with self.assertRaises(ReconcileError) as raised:
                        self.reconcile_with_payload(attempt_id, payload)
                    self.assertEqual("attempt_not_reconcilable", raised.exception.code)
                finally:
                    with Session(self.engine) as session:
                        attempt = session.get(WorkflowAttempt, attempt_id)
                        step = session.get(WorkflowStep, attempt.step_id)
                        session.delete(attempt)
                        step.status = "waiting"
                        session.commit()

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

    def test_cancel_rejects_each_ownership_or_scheduler_identity_mismatch(self):
        outcome, valid_payload = self.accepted_attempt()
        cases = {
            "job_name": ("name", "foreign-job"),
            "working_directory": ("current_working_directory", str(self.root / "sibling")),
            "comment": ("comment", "lmatelab:workflow=wrong;attempt=wrong"),
            "database_job_id": ("job_id", 99999),
            "user_name": ("user_name", "another-user"),
            "missing_comment": ("comment", None),
        }
        for label, (field, value) in cases.items():
            with self.subTest(label=label):
                payload = json.loads(json.dumps(valid_payload))
                if value is None:
                    payload["jobs"][0].pop(field)
                else:
                    payload["jobs"][0][field] = value
                executor = SequenceExecutor(response(stdout=json.dumps(payload).encode()))
                slurm = SlurmClient(
                    binaries=fixed_binaries(),
                    executor=executor,
                    workflow_root=self.workflow_root,
                    allowed_scripts=(self.script,),
                )
                reconciler = CompetitionReconciler(
                    slurm=slurm,
                    probe_script=self.script,
                    slurm_user="pb23030683",
                )
                with Session(self.engine) as session:
                    with self.assertRaises(ReconcileError) as raised:
                        reconciler.cancel_attempt(session, self.workflow_id, outcome.attempt_id)
                self.assertEqual("cancellation_ownership_mismatch", raised.exception.code)
                self.assertEqual(1, len(executor.calls))
                self.assertEqual(
                    ["/usr/bin/scontrol", "--json", "show", "job", outcome.job_id],
                    executor.calls[0][0],
                )

    def test_cancel_rejects_terminal_jobs_without_calling_scancel(self):
        outcome, payload = self.accepted_attempt()
        payload["jobs"][0]["job_state"] = ["COMPLETED"]
        executor = SequenceExecutor(response(stdout=json.dumps(payload).encode()))
        reconciler = CompetitionReconciler(
            slurm=SlurmClient(
                binaries=fixed_binaries(),
                executor=executor,
                workflow_root=self.workflow_root,
                allowed_scripts=(self.script,),
            ),
            probe_script=self.script,
            slurm_user="pb23030683",
        )

        with Session(self.engine) as session:
            with self.assertRaises(ReconcileError) as raised:
                reconciler.cancel_attempt(session, self.workflow_id, outcome.attempt_id)

        self.assertEqual("job_not_active", raised.exception.code)
        self.assertEqual(1, len(executor.calls))

    def test_owned_active_attempt_is_cancelled_and_evidence_is_persisted(self):
        outcome, payload = self.accepted_attempt()
        executor = SequenceExecutor(
            response(stdout=json.dumps(payload).encode()),
            response(),
        )
        reconciler = CompetitionReconciler(
            slurm=SlurmClient(
                binaries=fixed_binaries(),
                executor=executor,
                workflow_root=self.workflow_root,
                allowed_scripts=(self.script,),
            ),
            probe_script=self.script,
            slurm_user="pb23030683",
        )

        with Session(self.engine) as session:
            result = reconciler.cancel_attempt(session, self.workflow_id, outcome.attempt_id)

        self.assertEqual("cancelling", result.status)
        self.assertEqual(["/usr/bin/scancel", outcome.job_id], executor.calls[1][0])
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, outcome.attempt_id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            metadata = json.loads(attempt.metadata_json)
            self.assertEqual(("cancelling", "cancelling", "cancelling"), (attempt.status, step.status, run.status))
            self.assertEqual("RUNNING", metadata["before_cancel"]["raw_state"])
            self.assertEqual("requested", metadata["cancel_result"]["result"])
            event_row = session.scalar(
                select(WorkflowEvent).where(WorkflowEvent.event_type == "cancellation_requested")
            )
            self.assertIsNotNone(event_row)

    def test_completion_race_after_scancel_failure_records_real_terminal_state(self):
        outcome, running = self.accepted_attempt()
        completed = json.loads(json.dumps(running))
        completed["jobs"][0]["job_state"] = ["COMPLETED"]
        executor = SequenceExecutor(
            response(stdout=json.dumps(running).encode()),
            response(stderr=b"already completing", returncode=1),
            response(stdout=json.dumps(completed).encode()),
        )
        reconciler = CompetitionReconciler(
            slurm=SlurmClient(
                binaries=fixed_binaries(),
                executor=executor,
                workflow_root=self.workflow_root,
                allowed_scripts=(self.script,),
            ),
            probe_script=self.script,
            slurm_user="pb23030683",
        )

        with Session(self.engine) as session:
            result = reconciler.cancel_attempt(session, self.workflow_id, outcome.attempt_id)

        self.assertEqual("succeeded", result.status)
        self.assertEqual(["/usr/bin/scancel", outcome.job_id], executor.calls[1][0])
        self.assertEqual(["/usr/bin/squeue", "--json", f"--jobs={outcome.job_id}"], executor.calls[2][0])
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, outcome.attempt_id)
            self.assertEqual("succeeded", attempt.status)
            self.assertEqual(
                "cancellation_raced_terminal",
                session.scalar(
                    select(WorkflowEvent.event_type).where(
                        WorkflowEvent.event_type == "cancellation_raced_terminal"
                    )
                ),
            )

    def test_scancel_failure_preserves_snapshots_without_changing_active_state(self):
        outcome, running = self.accepted_attempt()
        executor = SequenceExecutor(
            response(stdout=json.dumps(running).encode()),
            response(stderr=b"scheduler private rejection", returncode=1),
            response(stdout=json.dumps(running).encode()),
        )
        reconciler = CompetitionReconciler(
            slurm=SlurmClient(
                binaries=fixed_binaries(),
                executor=executor,
                workflow_root=self.workflow_root,
                allowed_scripts=(self.script,),
            ),
            probe_script=self.script,
            slurm_user="pb23030683",
        )

        with Session(self.engine) as session:
            with self.assertRaises(ReconcileError) as raised:
                reconciler.cancel_attempt(session, self.workflow_id, outcome.attempt_id)

        self.assertEqual("cancellation_failed", raised.exception.code)
        self.assertNotIn("scheduler private rejection", str(raised.exception))
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, outcome.attempt_id)
            metadata = json.loads(attempt.metadata_json)
            self.assertEqual("queued", attempt.status)
            self.assertEqual("RUNNING", metadata["before_cancel"]["raw_state"])
            self.assertEqual("failed", metadata["cancel_result"]["result"])
            self.assertEqual("RUNNING", metadata["cancel_result"]["scheduler"]["raw_state"])
            self.assertIsNotNone(
                session.scalar(
                    select(WorkflowEvent).where(
                        WorkflowEvent.event_type == "cancellation_failed"
                    )
                )
            )

    @staticmethod
    def payload_with_state(payload, raw_state, exit_code="0:0"):
        changed = json.loads(json.dumps(payload))
        changed["jobs"][0]["job_state"] = [raw_state]
        return_code, signal = (int(part) for part in exit_code.split(":"))
        changed["jobs"][0]["exit_code"] = {
            "return_code": {"number": return_code},
            "signal": {"id": {"number": signal}},
        }
        return changed

    def accepted_vasp_attempt(self, step_key="scf"):
        attempt_id = str(uuid.uuid4())
        attempt_directory = self.slurm.prepare_attempt_directory(
            self.workflow_id,
            attempt_id,
        )
        submission = SlurmSubmission(
            workflow_id=self.workflow_id,
            attempt_id=attempt_id,
            step_key=step_key,
            attempt_number=1,
            attempt_directory=attempt_directory,
            script_path=self.vasp_script,
            runner_kind="vasp",
            runner_mode=step_key,
        )
        with Session(self.engine) as session:
            run = session.get(WorkflowRun, self.workflow_id)
            step = session.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_id == self.workflow_id,
                    WorkflowStep.step_key == step_key,
                )
            )
            run.status = "running"
            step.status = "queued"
            session.add(
                WorkflowAttempt(
                    id=attempt_id,
                    step_id=step.id,
                    attempt_number=1,
                    status="queued",
                    slurm_job_id="51020",
                    working_directory=str(attempt_directory),
                    metadata_json={
                        "comment": submission.comment,
                        "job_name": submission.job_name,
                        "runner_kind": "vasp",
                        "runner_mode": step_key,
                        "script_path": str(self.vasp_script.resolve()),
                        "script_sha256": submission.script_sha256,
                    },
                )
            )
            session.commit()
        return attempt_id, {
            "jobs": [
                {
                    "job_id": 51020,
                    "name": submission.job_name,
                    "job_state": ["RUNNING"],
                    "exit_code": {
                        "return_code": {"number": 0},
                        "signal": {"id": {"number": 0}},
                    },
                    "state_reason": "None",
                    "current_working_directory": str(attempt_directory),
                    "comment": submission.comment,
                    "user_name": "pb23030683",
                    "nodes": "anode02",
                }
            ]
        }

    def test_scheduler_identity_rejects_valid_runner_metadata_reinterpretation(self):
        attempt_id, payload = self.accepted_vasp_attempt(step_key="relax")
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, attempt_id)
            probe = SlurmSubmission(
                workflow_id=self.workflow_id,
                attempt_id=attempt_id,
                step_key="relax",
                attempt_number=attempt.attempt_number,
                attempt_directory=Path(attempt.working_directory),
                script_path=self.script,
                runner_kind="probe",
                runner_mode="success",
            )
            metadata = json.loads(attempt.metadata_json)
            metadata.update(
                {
                    "comment": probe.comment,
                    "job_name": probe.job_name,
                    "runner_kind": "probe",
                    "runner_mode": "success",
                    "script_path": str(self.script.resolve()),
                    "script_sha256": probe.script_sha256,
                }
            )
            attempt.metadata_json = metadata
            session.commit()

        result = self.reconcile_with_payload(
            attempt_id,
            self.payload_with_state(payload, "COMPLETED", "0:0"),
        )

        self.assertEqual(("unknown", True), (result.status, result.stale))
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, attempt_id)
            self.assertNotIn(attempt.status, {"succeeded", "awaiting_acceptance"})

    def test_reconcile_rejects_script_changed_at_the_claimed_path(self):
        outcome, payload = self.accepted_attempt()
        self.script.write_text("#!/bin/bash\necho changed\n", encoding="utf-8")

        with self.assertRaises(ReconcileError) as raised:
            self.reconcile_with_payload(outcome.attempt_id, payload)

        self.assertEqual("attempt_not_reconcilable", raised.exception.code)

    def test_cancel_terminal_classification_rejects_changed_script(self):
        outcome, running = self.accepted_attempt()
        completed = self.payload_with_state(running, "COMPLETED", "0:0")
        self.script.write_text("#!/bin/bash\necho changed\n", encoding="utf-8")
        executor = SequenceExecutor(
            response(stdout=json.dumps(running).encode()),
            response(stderr=b"already completing", returncode=1),
            response(stdout=json.dumps(completed).encode()),
        )
        reconciler = CompetitionReconciler(
            slurm=SlurmClient(
                binaries=fixed_binaries(),
                executor=executor,
                workflow_root=self.workflow_root,
                allowed_scripts=(self.script,),
            ),
            probe_script=self.script,
            slurm_user="pb23030683",
        )

        with Session(self.engine) as session, self.assertRaises(ReconcileError) as raised:
            reconciler.cancel_attempt(session, self.workflow_id, outcome.attempt_id)

        self.assertEqual("cancellation_ownership_mismatch", raised.exception.code)

    def test_cancel_terminal_classification_rejects_changed_scheduler_identity(self):
        outcome, running = self.accepted_attempt()
        completed = self.payload_with_state(running, "COMPLETED", "0:0")
        completed["jobs"][0]["comment"] = "lmatelab:workflow=wrong;attempt=wrong"
        executor = SequenceExecutor(
            response(stdout=json.dumps(running).encode()),
            response(stderr=b"already completing", returncode=1),
            response(stdout=json.dumps(completed).encode()),
        )
        reconciler = CompetitionReconciler(
            slurm=SlurmClient(
                binaries=fixed_binaries(),
                executor=executor,
                workflow_root=self.workflow_root,
                allowed_scripts=(self.script,),
            ),
            probe_script=self.script,
            slurm_user="pb23030683",
        )

        with Session(self.engine) as session, self.assertRaises(ReconcileError) as raised:
            reconciler.cancel_attempt(session, self.workflow_id, outcome.attempt_id)

        self.assertEqual("cancellation_ownership_mismatch", raised.exception.code)

    def reconcile_with_payload(self, attempt_id, payload):
        reconciler = CompetitionReconciler(
            slurm=SlurmClient(
                binaries=fixed_binaries(),
                executor=SequenceExecutor(response(stdout=json.dumps(payload).encode())),
                workflow_root=self.workflow_root,
                allowed_scripts=(self.script,),
            ),
            probe_script=self.script,
            vasp_script=self.vasp_script,
            slurm_user="pb23030683",
        )
        with Session(self.engine) as session:
            return reconciler.reconcile_attempt(session, attempt_id)

    def test_completed_vasp_job_waits_for_scientific_acceptance(self):
        attempt_id, payload = self.accepted_vasp_attempt()

        result = self.reconcile_with_payload(
            attempt_id,
            self.payload_with_state(payload, "COMPLETED", "0:0"),
        )

        self.assertEqual("awaiting_acceptance", result.status)
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, attempt_id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            self.assertEqual("awaiting_acceptance", attempt.status)
            self.assertEqual("awaiting_acceptance", step.status)
            self.assertEqual("running", run.status)

    def test_nonzero_vasp_slurm_result_is_scheduler_failed(self):
        attempt_id, payload = self.accepted_vasp_attempt()

        result = self.reconcile_with_payload(
            attempt_id,
            self.payload_with_state(payload, "COMPLETED", "1:0"),
        )

        self.assertEqual("failed", result.status)
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, attempt_id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            self.assertEqual(("failed", "failed", "failed"), (attempt.status, step.status, run.status))

    def test_vasp_completion_race_after_cancel_waits_for_scientific_acceptance(self):
        attempt_id, running = self.accepted_vasp_attempt()
        completed = self.payload_with_state(running, "COMPLETED", "0:0")
        executor = SequenceExecutor(
            response(stdout=json.dumps(running).encode()),
            response(stderr=b"already completing", returncode=1),
            response(stdout=json.dumps(completed).encode()),
        )
        reconciler = CompetitionReconciler(
            slurm=SlurmClient(
                binaries=fixed_binaries(),
                executor=executor,
                workflow_root=self.workflow_root,
                allowed_scripts=(self.script, self.vasp_script),
            ),
            probe_script=self.script,
            vasp_script=self.vasp_script,
            slurm_user="pb23030683",
        )

        with Session(self.engine) as session:
            result = reconciler.cancel_attempt(session, self.workflow_id, attempt_id)

        self.assertEqual("awaiting_acceptance", result.status)
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, attempt_id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            self.assertEqual("awaiting_acceptance", attempt.status)
            self.assertEqual("awaiting_acceptance", step.status)
            self.assertEqual("running", run.status)

    def test_fresh_probe_reconcilers_advance_queued_running_and_completed_states(self):
        outcome, base = self.accepted_attempt()
        observed = []
        for raw_state, expected in (
            ("PENDING", "queued"),
            ("RUNNING", "running"),
            ("COMPLETED", "succeeded"),
        ):
            result = self.reconcile_with_payload(
                outcome.attempt_id,
                self.payload_with_state(base, raw_state),
            )
            observed.append((result.raw_state, result.status))

        self.assertEqual(
            [("PENDING", "queued"), ("RUNNING", "running"), ("COMPLETED", "succeeded")],
            observed,
        )
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, outcome.attempt_id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            self.assertEqual("succeeded", attempt.status)
            self.assertEqual("succeeded", step.status)
            self.assertEqual("running", run.status)
            self.assertIsNotNone(attempt.finished_at)

    def assert_terminal_reconciliation(self, raw_state, exit_code, expected):
        outcome, base = self.accepted_attempt()
        result = self.reconcile_with_payload(
            outcome.attempt_id,
            self.payload_with_state(base, raw_state, exit_code),
        )

        self.assertEqual(expected, result.status)
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, outcome.attempt_id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            self.assertEqual((expected, expected, expected), (attempt.status, step.status, run.status))

    def test_fresh_reconciler_persists_failed_terminal_state(self):
        self.assert_terminal_reconciliation("FAILED", "1:0", "failed")

    def test_fresh_reconciler_persists_cancelled_terminal_state(self):
        self.assert_terminal_reconciliation("CANCELLED", "0:15", "cancelled")

    def test_missing_live_and_accounting_records_become_unknown_stale_idempotently(self):
        outcome, _base = self.accepted_attempt()
        clocks = (
            datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 15, 10, 1, tzinfo=timezone.utc),
        )
        for observed_at in clocks:
            executor = SequenceExecutor(
                response(stdout=json.dumps({"jobs": []}).encode()),
                response(stderr=b"invalid job id", returncode=1),
                response(stderr=b"accounting unavailable", returncode=1),
            )
            reconciler = CompetitionReconciler(
                slurm=SlurmClient(
                    binaries=fixed_binaries(),
                    executor=executor,
                    workflow_root=self.workflow_root,
                    allowed_scripts=(self.script,),
                    clock=lambda value=observed_at: value,
                ),
                probe_script=self.script,
                slurm_user="pb23030683",
                clock=lambda value=observed_at: value,
            )
            with Session(self.engine) as session:
                result = reconciler.reconcile_attempt(session, outcome.attempt_id)
            self.assertEqual(("unknown", True), (result.status, result.stale))

        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, outcome.attempt_id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            metadata = json.loads(attempt.metadata_json)
            self.assertEqual(("unknown", "unknown", "unknown"), (attempt.status, step.status, run.status))
            self.assertTrue(metadata["scheduler_observation"]["stale"])
            self.assertEqual(
                "scheduler_record_unavailable",
                metadata["scheduler_observation"]["error_code"],
            )
            events = session.scalars(
                select(WorkflowEvent).where(
                    WorkflowEvent.workflow_id == self.workflow_id,
                    WorkflowEvent.event_type == "scheduler_state_changed",
                )
            ).all()
            self.assertEqual(1, len(events))


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
