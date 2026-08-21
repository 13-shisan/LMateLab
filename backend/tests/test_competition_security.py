import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path
from unittest import mock

from sqlalchemy.orm import Session

from services.competition_inputs import InputValidationError, _safe_filename, validate_draft_payload
from services.competition_reconcile import ReconcileError
from services.competition_slurm import SlurmClient
from tests.test_competition_coordinator import CoordinatorTestCase
from tests import test_competition_results as result_fixtures
from tests.test_competition_slurm import RecordingExecutor, fixed_binaries


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERIFY_RUNTIME = PROJECT_ROOT / "deploy" / "107cup" / "verify-runtime.sh"


class CompetitionInputSecurityTests(unittest.TestCase):
    def test_illegal_and_oversized_audit_filenames_are_rejected(self):
        invalid = (
            "",
            " POSCAR",
            "POSCAR ",
            "../POSCAR",
            "nested/POSCAR",
            "nested\\POSCAR",
            "POS\x00CAR",
            "POS\nCAR",
            "x" * 256,
        )
        for filename in invalid:
            with self.subTest(filename=repr(filename)):
                with self.assertRaises(InputValidationError):
                    _safe_filename(filename)
        self.assertEqual("结构.vasp", _safe_filename("结构.vasp"))

    def test_parameter_and_route_injection_never_become_scheduler_arguments(self):
        base = {
            "template_version": "mos2_v1",
            "source_kind": "builtin",
            "steps": ["relax", "scf", "band", "dos"],
            "parameters": {},
        }
        injected = (
            {**base, "parameters": {"relax": {"SYSTEM": "MoS2; scancel 1"}}},
            {**base, "parameters": {"relax": {"ENCUT": "520; scancel 1"}}},
            {**base, "steps": ["relax", "scf; sbatch /tmp/x", "band", "dos"]},
        )
        for payload in injected:
            with self.subTest(payload=payload):
                with self.assertRaises(InputValidationError):
                    validate_draft_payload(payload)

        executor = RecordingExecutor()
        client = SlurmClient(binaries=fixed_binaries(), executor=executor)
        for job_id in ("41001; scancel 1", "$(scancel 1)", "41001.batch", "../41001"):
            with self.subTest(job_id=job_id):
                with self.assertRaises(ValueError):
                    client.observe(job_id)
        self.assertEqual([], executor.calls)

    def test_logs_are_fixed_name_bounded_and_symlinks_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow_root = root / "workflows"
            workflow_id = str(uuid.uuid4())
            attempt_id = str(uuid.uuid4())
            client = SlurmClient(
                binaries=fixed_binaries(),
                executor=RecordingExecutor(),
                workflow_root=workflow_root,
                max_log_tail_bytes=16,
            )
            attempt_dir = client.prepare_attempt_directory(workflow_id, attempt_id)
            (attempt_dir / "stdout.log").write_bytes(b"a" * 4096 + b"TRUSTED-LOG-TAIL")
            self.assertEqual(
                "TRUSTED-LOG-TAIL",
                client.read_log_tail(workflow_id, attempt_id, "stdout"),
            )
            for stream in ("../stdout", "/etc/passwd", "job-id.receipt", "combined"):
                with self.subTest(stream=stream):
                    with self.assertRaises(ValueError):
                        client.read_log_tail(workflow_id, attempt_id, stream)

            original_is_symlink = Path.is_symlink

            def report_log_symlink(path):
                return path.name == "stdout.log" or original_is_symlink(path)

            with mock.patch.object(Path, "is_symlink", autospec=True, side_effect=report_log_symlink):
                with self.assertRaises(ValueError):
                    client.read_log_tail(workflow_id, attempt_id, "stdout")


class CompetitionOwnershipSecurityTests(CoordinatorTestCase):
    def test_foreign_scheduler_identity_cannot_be_cancelled_viewed_as_trusted_or_advanced(self):
        self.start()
        attempt = self.latest_attempt("relax")
        self.slurm.set_state(
            attempt.id,
            "running",
            raw_state="RUNNING",
            exit_code="0:0",
            identity_matches=False,
        )
        with self.SessionLocal() as session:
            with self.assertRaises(ReconcileError) as raised:
                self.reconciler.cancel_attempt(session, self.workflow_id, attempt.id)
        self.assertEqual("cancellation_ownership_mismatch", raised.exception.code)
        self.assertEqual([], self.slurm.cancelled_jobs)

        tick = self.new_coordinator().tick_once()
        current = self.latest_attempt("relax")
        observation = json.loads(current.metadata_json)["scheduler_observation"]
        self.assertEqual((1, 0), (tick.processed, tick.failures))
        self.assertEqual("unknown", current.status)
        self.assertTrue(observation["stale"])
        self.assertEqual("scheduler_ownership_mismatch", observation["error_code"])
        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual(0, self.attempt_count("scf"))


@unittest.skipIf(os.name == "nt", "atomic symlink rollback is verified on 107 Linux")
class CompetitionRollbackImmutabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = result_fixtures.CompetitionResultServiceTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_release_pointer_rollback_does_not_mutate_attempts_or_evidence_bundle(self):
        with Session(self.fixture.engine) as session:
            run = self.fixture._load(session, result_fixtures.WORKFLOW_ID)
            before_bundle = self.fixture.service.artifact(
                session, run, "evidence-bundle"
            ).content
            before_attempts = [
                (
                    attempt.id,
                    attempt.status,
                    attempt.slurm_job_id,
                    attempt.metadata_json,
                )
                for step in run.steps
                for attempt in step.attempts
            ]

        releases = self.fixture.releases_root
        old_release = releases / ("a" * 40)
        new_release = releases / ("b" * 40)
        new_release.mkdir()
        manifest = f"{'3' * 64}  source/backend/main_107cup.py\n"
        (new_release / "manifest.txt").write_text(manifest, encoding="utf-8")
        digest = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
        (new_release / "manifest.sha256").write_text(
            f"{digest}  manifest.txt\n", encoding="ascii"
        )
        current = self.fixture.root / "current"
        current.symlink_to(new_release, target_is_directory=True)
        replacement = self.fixture.root / "current.next"
        replacement.symlink_to(old_release, target_is_directory=True)
        os.replace(replacement, current)
        self.assertEqual(old_release.resolve(), current.resolve())

        with Session(self.fixture.engine) as session:
            run = self.fixture._load(session, result_fixtures.WORKFLOW_ID)
            after_bundle = self.fixture.service.artifact(
                session, run, "evidence-bundle"
            ).content
            after_attempts = [
                (
                    attempt.id,
                    attempt.status,
                    attempt.slurm_job_id,
                    attempt.metadata_json,
                )
                for step in run.steps
                for attempt in step.attempts
            ]
        self.assertEqual(before_bundle, after_bundle)
        self.assertEqual(before_attempts, after_attempts)


class RuntimeVerifierSecurityContractTests(unittest.TestCase):
    def test_runtime_verifier_is_bounded_read_only_and_gateway_identity_bound(self):
        source = VERIFY_RUNTIME.read_text(encoding="utf-8")
        for required in (
            "timeout 15 squeue",
            "timeout 15 sacct",
            "--connect-timeout 3 --max-time 10",
            "LMATELAB_VERIFY_PUBLIC_URL",
            "public gateway does not target the verified 107 runtime",
            "service-manifest-sha256",
            "sha256sum -c manifest.sha256",
            "PRAGMA integrity_check",
            "unexpected LMateLab process found on the login node",
        ):
            self.assertIn(required, source)
        self.assertNotRegex(
            source,
            r"(?m)^\s*(?:sbatch|scancel|uvicorn|pip\s+install|npm\s)",
        )


@unittest.skipUnless(os.name == "posix", "runtime verifier execution is validated on 107 Linux")
class RuntimeVerifierExecutionTests(unittest.TestCase):
    @staticmethod
    def _write_executable(path: Path, source: str) -> None:
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name) / "lmatelab-107cup"
        self.runtime = self.root / "runtime"
        self.release = self.root / "releases" / ("a" * 40)
        self.fake_bin = self.root / "fake-bin"
        for path in (self.runtime, self.release, self.fake_bin, self.root / "data" / "db"):
            path.mkdir(parents=True, exist_ok=True)
        (self.root / "current").symlink_to(self.release, target_is_directory=True)
        (self.release / "commit.txt").write_text("a" * 40 + "\n", encoding="ascii")
        manifest = f"{'b' * 64}  source/backend/main_107cup.py\n"
        (self.release / "manifest.txt").write_text(manifest, encoding="utf-8")
        manifest_sha = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
        (self.release / "manifest.sha256").write_text(
            f"{manifest_sha}  manifest.txt\n", encoding="ascii"
        )
        values = {
            "service-job-id": "41001",
            "service-node": "anode18",
            "service-port": "18731",
            "service-commit": "a" * 40,
            "service-manifest-sha256": manifest_sha,
        }
        for name, value in values.items():
            (self.runtime / name).write_text(value + "\n", encoding="ascii")
        (self.runtime / "service-state.json").write_text(
            json.dumps(
                {
                    "schema": "lmatelab-107cup-service-state-v1",
                    "job_id": "41001",
                    "node": "anode18",
                    "port": 18731,
                    "commit": "a" * 40,
                    "manifest_sha256": manifest_sha,
                    "started_at": "2026-08-20T09:00:00+08:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        for name in ("eln.db", "digests.db"):
            with sqlite3.connect(self.root / "data" / "db" / name) as connection:
                connection.execute("CREATE TABLE health (id INTEGER)")

        self.local_live = self.root / "local-live.json"
        self.public_live = self.root / "public-live.json"
        self.ready = self.root / "ready.json"
        live = {
            "status": "ok",
            "job_id": "41001",
            "node": "anode18",
            "commit": "a" * 40,
            "manifest_sha256": manifest_sha,
            "started_at": "2026-08-20T09:00:00+08:00",
            "release_kind": "stable",
            "data_mode": "live",
        }
        self.local_live.write_text(json.dumps(live), encoding="utf-8")
        self.public_live.write_text(json.dumps(live), encoding="utf-8")
        self.ready.write_text('{"status":"ready"}\n', encoding="utf-8")

        for command in ("squeue", "sacct"):
            self._write_executable(
                self.fake_bin / command,
                """
                #!/bin/bash
                exit 0
                """,
            )
        self._write_executable(
            self.fake_bin / "pgrep",
            """
            #!/bin/bash
            exit 1
            """,
        )
        self._write_executable(
            self.fake_bin / "curl",
            """
            #!/bin/bash
            set -euo pipefail
            destination=
            url=
            while test "$#" -gt 0; do
              case "$1" in
                --output) destination=$2; shift 2 ;;
                --*) shift ;;
                *) url=$1; shift ;;
              esac
            done
            case "$url" in
              *public.invalid*/api/health/live) source_file=$PUBLIC_LIVE ;;
              */api/health/live) source_file=$LOCAL_LIVE ;;
              */api/health/ready) source_file=$READY ;;
              *) exit 90 ;;
            esac
            cp "$source_file" "$destination"
            """,
        )

    def _run_verifier(self):
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.fake_bin}{os.pathsep}{env['PATH']}",
                "LMATELAB_ROOT": str(self.root),
                "LMATELAB_VERIFY_PUBLIC_URL": "http://public.invalid:18733",
                "LOCAL_LIVE": str(self.local_live),
                "PUBLIC_LIVE": str(self.public_live),
                "READY": str(self.ready),
            }
        )
        return subprocess.run(
            ["/bin/bash", str(VERIFY_RUNTIME)],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_gateway_identity_match_passes_and_old_job_target_fails_closed(self):
        passed = self._run_verifier()
        self.assertEqual(0, passed.returncode, passed.stderr)
        self.assertIn("verified_job_id=41001", passed.stdout)

        stale = json.loads(self.public_live.read_text(encoding="utf-8"))
        stale["job_id"] = "40999"
        self.public_live.write_text(json.dumps(stale), encoding="utf-8")
        failed = self._run_verifier()
        self.assertNotEqual(0, failed.returncode)
        self.assertIn("public gateway does not target", failed.stderr)


if __name__ == "__main__":
    unittest.main()
