from __future__ import annotations

import importlib.util
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, filename: str):
    path = ROOT / "deploy" / "107cup" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DatabasePreparationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.module = load_script("prepare_databases_under_test", "prepare-databases.py")
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.module.ROOT = self.root
        self.module.DATA_ROOT = self.root / "data" / "db"
        self.module.BACKUP_ROOT = self.root / "backups"
        self.module.DATA_ROOT.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def test_backup_is_consistent_private_and_never_overwritten(self):
        database = self.module.DATA_ROOT / "eln.db"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence VALUES ('kept')")
        connection.commit()
        connection.close()

        backup = self.module.backup_database(
            database, self.module.BACKUP_ROOT / "pre-migration", "123.0"
        )
        self.assertIsNotNone(backup)
        if os.name == "posix":
            self.assertEqual(0, backup.stat().st_mode & 0o077)
        copied = sqlite3.connect(backup)
        try:
            self.assertEqual(("kept",), copied.execute("SELECT value FROM evidence").fetchone())
        finally:
            copied.close()
        with self.assertRaises(FileExistsError):
            self.module.backup_database(
                database, self.module.BACKUP_ROOT / "pre-migration", "123.0"
            )

    def test_verify_rejects_a_corrupt_database(self):
        database = self.module.DATA_ROOT / "eln.db"
        database.write_bytes(b"not sqlite")
        with self.assertRaises(sqlite3.DatabaseError):
            self.module.verify_database(database)


class AgentWorkerControlRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.module = load_script("agent_worker_control_under_test", "agent_worker_control.py")
        self.temporary = tempfile.TemporaryDirectory()
        self.module.ROOT = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def owned_job(job_id: str = "123") -> dict[str, str]:
        return {
            "JobId": job_id,
            "JobName": "lmatelab-agent-worker",
            "UserName": "pb23030683",
            "Command": "/home/scc/pb23030683/projects/LMateLab-107Cup/deploy/107cup/agent-worker.slurm",
            "WorkDir": "/home/scc/pb23030683/projects/LMateLab-107Cup",
            "Account": "competition",
            "Partition": "P107-A100",
            "QOS": "qos_p107-a100",
        }

    def test_recover_reuses_the_only_owned_worker(self):
        with (
            mock.patch.object(self.module, "_lock", return_value=nullcontext()),
            mock.patch.object(self.module, "_active_workers", return_value=[self.owned_job()]),
            mock.patch.object(self.module, "_atomic_json") as publish,
            mock.patch.object(self.module.subprocess, "run") as run,
        ):
            with redirect_stdout(io.StringIO()):
                self.assertEqual("123", self.module.recover())
        run.assert_not_called()
        self.assertEqual("reused", publish.call_args.args[1]["action"])

    def test_recover_submits_once_when_no_worker_exists(self):
        completed = SimpleNamespace(returncode=0, stdout="456;training\n", stderr="")
        with (
            mock.patch.object(self.module, "_lock", return_value=nullcontext()),
            mock.patch.object(self.module, "_active_workers", return_value=[]),
            mock.patch.object(self.module, "_atomic_json") as publish,
            mock.patch.object(self.module.subprocess, "run", return_value=completed) as run,
        ):
            with redirect_stdout(io.StringIO()):
                self.assertEqual("456", self.module.recover())
        self.assertEqual(1, run.call_count)
        self.assertEqual("submitted", publish.call_args.args[1]["action"])

    def test_recover_fails_closed_on_duplicate_workers(self):
        with (
            mock.patch.object(self.module, "_lock", return_value=nullcontext()),
            mock.patch.object(
                self.module,
                "_active_workers",
                return_value=[self.owned_job("123"), self.owned_job("124")],
            ),
            mock.patch.object(self.module, "_atomic_json"),
            mock.patch.object(self.module.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(
                self.module.AgentWorkerControlError, "multiple_owned_workers"
            ):
                self.module.recover()
        run.assert_not_called()

    def test_stopping_old_worker_does_not_overwrite_new_worker_state(self):
        state_path = self.module.ROOT / "runtime" / "agent-worker-state.json"
        state_path.parent.mkdir(parents=True)
        current = {
            "schema": self.module.STATE_SCHEMA,
            "job_id": "124",
            "status": "running",
        }
        state_path.write_text(json.dumps(current), encoding="utf-8")
        arguments = SimpleNamespace(
            job_id="123",
            node="anode17",
            commit="a" * 40,
            manifest_sha256="b" * 64,
            started_at="2026-09-15T12:30:44+08:00",
            status="stopped",
            exit_code=143,
        )

        with mock.patch.object(self.module, "_lookup", return_value=self.owned_job("123")):
            self.module.publish(arguments)

        self.assertEqual(current, json.loads(state_path.read_text(encoding="utf-8")))

    def test_stopping_current_worker_updates_its_own_state(self):
        state_path = self.module.ROOT / "runtime" / "agent-worker-state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps({
                "schema": self.module.STATE_SCHEMA,
                "job_id": "123",
                "status": "running",
            }),
            encoding="utf-8",
        )
        arguments = SimpleNamespace(
            job_id="123",
            node="anode17",
            commit="a" * 40,
            manifest_sha256="b" * 64,
            started_at="2026-09-15T12:30:44+08:00",
            status="stopped",
            exit_code=143,
        )

        with mock.patch.object(self.module, "_lookup", return_value=self.owned_job("123")):
            self.module.publish(arguments)

        updated = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual("123", updated["job_id"])
        self.assertEqual("stopped", updated["status"])
        self.assertEqual(143, updated["exit_code"])


class QoderReleaseRuntimeTests(unittest.TestCase):
    def test_install_endpoint_only_verifies_the_build_installed_release(self):
        from services import qoder_management

        expected = {"installed": True, "manageable": True}
        with (
            mock.patch.dict(
                "os.environ", {"LMATELAB_QODER_MANAGEMENT_ENABLED": "1"}, clear=True
            ),
            mock.patch.object(qoder_management, "version", return_value="1.0.14"),
            mock.patch.object(qoder_management, "_cli_path", return_value=Path("qoderclicn")),
            mock.patch.object(qoder_management, "qoder_status", return_value=expected),
            mock.patch.object(qoder_management.subprocess, "run") as run,
        ):
            self.assertEqual(expected, qoder_management.install_qoder())
        run.assert_not_called()

    def test_install_endpoint_rejects_a_version_mismatch(self):
        from services import qoder_management

        with (
            mock.patch.dict(
                "os.environ", {"LMATELAB_QODER_MANAGEMENT_ENABLED": "1"}, clear=True
            ),
            mock.patch.object(qoder_management, "version", return_value="1.0.13"),
        ):
            with self.assertRaisesRegex(
                qoder_management.QoderManagementError, "version mismatch"
            ):
                qoder_management.install_qoder()

    def test_login_url_accepts_only_qoder_cn_device_challenges(self):
        from services import qoder_management

        expected = "https://qoder.cn/device/selectAccounts?challenge=sample"
        self.assertEqual(expected, qoder_management._extract_login_url(f"Open {expected}"))
        self.assertEqual(
            "https://qoder.com.cn/device/selectAccounts?challenge=sample",
            qoder_management._extract_login_url(
                "Open https://qoder.com.cn/device/selectAccounts?challenge=sample"
            ),
        )
        for rejected in (
            "https://qoder.com/device/selectAccounts?challenge=sample",
            "https://qoder.cn/account/integrations?challenge=sample",
            "https://qoder.cn/device/selectAccounts",
        ):
            self.assertIsNone(qoder_management._extract_login_url(rejected))


if __name__ == "__main__":
    unittest.main()
