import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "deploy" / "107cup" / "service_recovery.py"


def load_module():
    spec = importlib.util.spec_from_file_location("service_recovery", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeScheduler:
    def __init__(self, records=None, submitted_job_id="41003"):
        self.records = dict(records or {})
        self.submitted_job_id = submitted_job_id
        self.submit_calls = []

    def lookup(self, job_id):
        return self.records.get(job_id)

    def submit(self, script, work_dir):
        self.submit_calls.append((script, work_dir))
        return self.submitted_job_id


class ServiceRecoveryTests(unittest.TestCase):
    commit = "a" * 40
    manifest = "b" * 64

    def setUp(self):
        self.module = load_module()
        self.temporary = tempfile.TemporaryDirectory(prefix="lmatelab-service-recovery-")
        self.root = Path(self.temporary.name)
        self.runtime = self.root / "runtime"
        self.project = self.root / "project"
        self.runtime.mkdir()
        (self.project / "deploy" / "107cup").mkdir(parents=True)
        self.service_script = self.project / "deploy" / "107cup" / "service.slurm"
        self.service_script.write_text("#!/bin/bash\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_compute_node_address_uses_the_fixed_107_internal_network(self):
        self.assertEqual("11.11.10.1", self.module.node_to_address("anode01"))
        self.assertEqual("11.11.10.26", self.module.node_to_address("anode26"))
        for invalid in ("anode00", "anode27", "anode1", "11.11.10.18", "anode18.local"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(self.module.RecoveryError):
                    self.module.node_to_address(invalid)

    def test_health_probe_uses_internal_address_but_keeps_node_identity_separate(self):
        requested = []

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _maximum):
                return json.dumps(self.payload).encode("utf-8")

        def urlopen(url, timeout):
            requested.append((url, timeout))
            if url.endswith("/live"):
                return Response({"status": "ok", "node": "anode18"})
            return Response({"status": "ready"})

        with patch.object(self.module.urllib.request, "urlopen", side_effect=urlopen):
            live, ready = self.module.probe_health("anode18", 18731)

        self.assertEqual({"status": "ok", "node": "anode18"}, live)
        self.assertEqual({"status": "ready"}, ready)
        self.assertEqual(
            [
                ("http://11.11.10.18:18731/api/health/live", 5),
                ("http://11.11.10.18:18731/api/health/ready", 5),
            ],
            requested,
        )

    def record(self, job_id, *, state="RUNNING", node="anode18", owned=True):
        return self.module.JobRecord(
            job_id=job_id,
            state=state,
            job_name="lmatelab-web" if owned else "foreign-job",
            user_name="pb23030683",
            command=str(self.service_script),
            work_dir=str(self.project),
            account="competition",
            partition="P107-A100",
            qos="qos_p107-a100",
            node=node,
        )

    def state_payload(self, job_id="41001", node="anode18"):
        return {
            "schema": "lmatelab-107cup-service-state-v1",
            "job_id": job_id,
            "node": node,
            "port": 18731,
            "commit": self.commit,
            "manifest_sha256": self.manifest,
            "started_at": "2026-08-21T12:00:00+08:00",
        }

    def write_json(self, name, payload):
        (self.runtime / name).write_text(
            json.dumps(payload), encoding="utf-8", newline="\n"
        )

    def controller(self, scheduler, health_probe):
        return self.module.ServiceRecovery(
            runtime_dir=self.runtime,
            project_dir=self.project,
            scheduler=scheduler,
            health_probe=health_probe,
            release_identity=lambda: (self.commit, self.manifest),
            clock=lambda: 1_000.0,
            retry_delay_seconds=300,
            max_attempts=3,
        )

    def test_ready_owned_service_is_reused_without_submission(self):
        payload = self.state_payload()
        self.write_json("service-state.json", payload)
        scheduler = FakeScheduler({"41001": self.record("41001")})
        controller = self.controller(
            scheduler,
            lambda _node, _port: (
                {
                    "status": "ok",
                    "job_id": "41001",
                    "node": "anode18",
                    "commit": self.commit,
                    "manifest_sha256": self.manifest,
                    "release_kind": "stable",
                    "data_mode": "live",
                },
                {"status": "ready"},
            ),
        )

        result = controller.run()

        self.assertEqual("ready", result["status"])
        self.assertEqual("41001", result["job_id"])
        self.assertEqual([], scheduler.submit_calls)

    def test_candidate_health_requires_its_own_runtime_identity(self):
        state = self.state_payload(job_id="41003", node="anode17")

        matching = self.module.verify_service_health(
            state,
            lambda _node, _port: (
                {
                    "status": "ok",
                    "job_id": "41003",
                    "node": "anode17",
                    "commit": self.commit,
                    "manifest_sha256": self.manifest,
                    "release_kind": "stable",
                    "data_mode": "live",
                },
                {"status": "ready"},
            ),
        )
        stale_same_port = self.module.verify_service_health(
            state,
            lambda _node, _port: (
                {
                    "status": "ok",
                    "job_id": "41001",
                    "node": "anode17",
                    "commit": "b" * 40,
                    "manifest_sha256": "c" * 64,
                    "release_kind": "stable",
                    "data_mode": "live",
                },
                {"status": "ready"},
            ),
        )

        self.assertEqual("ready", matching["status"])
        self.assertEqual(
            {"status": "blocked", "reason": "service_identity_mismatch"},
            stale_same_port,
        )

    def test_dead_service_submits_once_and_active_candidate_prevents_duplicate(self):
        self.write_json("service-state.json", self.state_payload(job_id="41000"))
        scheduler = FakeScheduler()
        controller = self.controller(scheduler, lambda *_args: self.fail("unexpected probe"))

        first = controller.run()

        self.assertEqual("submitted", first["status"])
        self.assertEqual("41003", first["job_id"])
        self.assertEqual(1, len(scheduler.submit_calls))
        recovery_state = json.loads(
            (self.runtime / "service-recovery-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual("41003", recovery_state["candidate_job_id"])
        self.assertEqual(1, recovery_state["attempt_count"])

        scheduler.records["41003"] = self.record("41003", state="PENDING", node="")
        second = controller.run()

        self.assertEqual("waiting", second["status"])
        self.assertEqual("candidate_active", second["reason"])
        self.assertEqual(1, len(scheduler.submit_calls))

    def test_foreign_candidate_fails_closed_without_submission(self):
        self.write_json("service-state.json", self.state_payload(job_id="41000"))
        self.write_json(
            "service-recovery-state.json",
            {
                "schema": "lmatelab-107cup-service-recovery-v1",
                "candidate_job_id": "41002",
                "attempt_count": 1,
                "submitted_at": 900.0,
            },
        )
        scheduler = FakeScheduler({"41002": self.record("41002", owned=False)})
        controller = self.controller(scheduler, lambda *_args: self.fail("unexpected probe"))

        result = controller.run()

        self.assertEqual("blocked", result["status"])
        self.assertEqual("candidate_ownership_mismatch", result["reason"])
        self.assertEqual([], scheduler.submit_calls)

    def test_running_but_unhealthy_service_waits_without_replacement(self):
        self.write_json("service-state.json", self.state_payload())
        scheduler = FakeScheduler({"41001": self.record("41001")})

        def unavailable(*_args):
            raise self.module.HealthProbeError("unavailable")

        result = self.controller(scheduler, unavailable).run()

        self.assertEqual("waiting", result["status"])
        self.assertEqual("service_not_ready", result["reason"])
        self.assertEqual([], scheduler.submit_calls)

    def test_retry_budget_blocks_submission_storm(self):
        self.write_json("service-state.json", self.state_payload(job_id="41000"))
        self.write_json(
            "service-recovery-state.json",
            {
                "schema": "lmatelab-107cup-service-recovery-v1",
                "candidate_job_id": "41002",
                "attempt_count": 3,
                "submitted_at": 600.0,
            },
        )
        scheduler = FakeScheduler()

        result = self.controller(scheduler, lambda *_args: self.fail("unexpected probe")).run()

        self.assertEqual("blocked", result["status"])
        self.assertEqual("retry_budget_exhausted", result["reason"])
        self.assertEqual([], scheduler.submit_calls)

    def test_publish_is_atomic_private_and_clears_matching_candidate(self):
        self.write_json(
            "service-recovery-state.json",
            {
                "schema": "lmatelab-107cup-service-recovery-v1",
                "candidate_job_id": "41003",
                "attempt_count": 2,
                "submitted_at": 900.0,
            },
        )

        payload = self.module.publish_service_state(
            runtime_dir=self.runtime,
            job_id="41003",
            node="anode18",
            port=18731,
            commit=self.commit,
            manifest_sha256=self.manifest,
            started_at="2026-08-21T12:00:00+08:00",
        )

        self.assertEqual(self.state_payload(job_id="41003"), payload)
        stored = json.loads((self.runtime / "service-state.json").read_text("utf-8"))
        self.assertEqual(payload, stored)
        self.assertEqual("41003", (self.runtime / "service-job-id").read_text().strip())
        if os.name != "nt":
            self.assertEqual(
                0o600, (self.runtime / "service-state.json").stat().st_mode & 0o777
            )
        recovery = json.loads(
            (self.runtime / "service-recovery-state.json").read_text("utf-8")
        )
        self.assertIsNone(recovery["candidate_job_id"])
        self.assertEqual(0, recovery["attempt_count"])


if __name__ == "__main__":
    unittest.main()
