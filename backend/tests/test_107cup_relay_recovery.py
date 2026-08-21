import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "deploy" / "107cup" / "relay" / "ensure_forward.py"


def load_module():
    spec = importlib.util.spec_from_file_location("ensure_forward", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeControl:
    def __init__(self, targets=None):
        self.targets = dict(targets or {})
        self.calls = []

    def forward(self, bind_port, target_host, target_port):
        self.calls.append(("forward", bind_port, target_host, target_port))
        if bind_port in self.targets:
            raise RuntimeError("bind collision")
        self.targets[bind_port] = (target_host, target_port)

    def cancel(self, bind_port, target_host, target_port):
        self.calls.append(("cancel", bind_port, target_host, target_port))
        if self.targets.get(bind_port) != (target_host, target_port):
            raise RuntimeError("forward identity mismatch")
        del self.targets[bind_port]


class FakeGateway:
    def __init__(self):
        self.ensure_calls = 0
        self.public_payload = None

    def ensure_running(self):
        self.ensure_calls += 1

    def probe_public(self):
        if self.public_payload is None:
            raise RuntimeError("public gateway unavailable")
        return self.public_payload, {"status": "ready"}


class RelayRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.temporary = tempfile.TemporaryDirectory(prefix="lmatelab-relay-recovery-")
        self.state_path = Path(self.temporary.name) / "forward-state.json"
        self.commit = "a" * 40
        self.manifest = "b" * 64
        self.desired = self.module.DesiredRuntime(
            job_id="41003",
            node="anode18",
            port=18731,
            commit=self.commit,
            manifest_sha256=self.manifest,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def live(self, desired=None):
        desired = desired or self.desired
        return {
            "status": "ok",
            "job_id": desired.job_id,
            "node": desired.node,
            "commit": desired.commit,
            "manifest_sha256": desired.manifest_sha256,
            "release_kind": "stable",
            "data_mode": "live",
        }

    def test_node_mapping_is_fixed_to_107_compute_network(self):
        self.assertEqual("11.11.10.1", self.module.node_to_target("anode01"))
        self.assertEqual("11.11.10.26", self.module.node_to_target("anode26"))
        for invalid in ("anode00", "anode27", "tradmin-02", "11.11.10.17"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.module.node_to_target(invalid)

    def test_maintenance_marker_must_be_a_small_regular_file(self):
        marker = Path(self.temporary.name) / "maintenance"
        self.assertFalse(self.module.maintenance_enabled(marker))
        marker.write_text("operator requested\n", encoding="utf-8")
        self.assertTrue(self.module.maintenance_enabled(marker))
        marker.write_text("x" * 257, encoding="utf-8")
        with self.assertRaises(self.module.RelayRecoveryError):
            self.module.maintenance_enabled(marker)

    def test_existing_matching_forward_is_adopted_without_rebind(self):
        target = self.module.node_to_target(self.desired.node)
        control = FakeControl({18740: (target, 18731)})
        gateway = FakeGateway()
        gateway.public_payload = self.live()

        def probe(port):
            self.assertEqual(18740, port)
            return self.live(), {"status": "ready"}

        result = self.module.ForwardReconciler(
            state_path=self.state_path,
            control=control,
            probe=probe,
            gateway=gateway,
        ).reconcile(self.desired)

        self.assertEqual("ready", result["status"])
        self.assertEqual([], control.calls)
        self.assertEqual(1, gateway.ensure_calls)
        stored = json.loads(self.state_path.read_text("utf-8"))
        self.assertEqual("anode18", stored["node"])

    def test_bootstrap_adopts_only_a_complete_healthy_existing_forward(self):
        desired = self.module.adopt_current_forward(
            self.state_path,
            lambda port: (self.live(), {"status": "ready"})
            if port == 18740
            else self.fail("unexpected port"),
        )

        self.assertEqual(self.desired, desired)
        self.assertEqual("11.11.10.18", json.loads(self.state_path.read_text())["target_host"])

        with self.assertRaises(self.module.RelayRecoveryError):
            self.module.adopt_current_forward(
                self.state_path,
                lambda _port: ({**self.live(), "commit": "A" * 40}, {"status": "ready"}),
            )

    def test_new_target_is_probed_before_old_forward_is_cancelled(self):
        old = self.module.DesiredRuntime(
            job_id="41001",
            node="anode17",
            port=18731,
            commit="c" * 40,
            manifest_sha256="d" * 64,
        )
        self.state_path.write_text(
            json.dumps(old.as_state()), encoding="utf-8", newline="\n"
        )
        control = FakeControl({18740: ("11.11.10.17", 18731)})
        gateway = FakeGateway()
        gateway.public_payload = self.live()

        def probe(port):
            target = control.targets[port]
            if target == ("11.11.10.18", 18731):
                return self.live(), {"status": "ready"}
            return self.live(old), {"status": "ready"}

        result = self.module.ForwardReconciler(
            state_path=self.state_path,
            control=control,
            probe=probe,
            gateway=gateway,
        ).reconcile(self.desired)

        self.assertEqual("switched", result["status"])
        self.assertEqual(
            [
                ("forward", 18742, "11.11.10.18", 18731),
                ("cancel", 18740, "11.11.10.17", 18731),
                ("forward", 18740, "11.11.10.18", 18731),
                ("cancel", 18742, "11.11.10.18", 18731),
            ],
            control.calls,
        )
        self.assertEqual(("11.11.10.18", 18731), control.targets[18740])

    def test_failed_probe_keeps_old_forward_untouched(self):
        old = self.module.DesiredRuntime(
            job_id="41001",
            node="anode17",
            port=18731,
            commit="c" * 40,
            manifest_sha256="d" * 64,
        )
        self.state_path.write_text(
            json.dumps(old.as_state()), encoding="utf-8", newline="\n"
        )
        control = FakeControl({18740: ("11.11.10.17", 18731)})
        gateway = FakeGateway()

        def probe(port):
            if port == 18742:
                raise self.module.RelayRecoveryError("candidate unavailable")
            return self.live(old), {"status": "ready"}

        reconciler = self.module.ForwardReconciler(
            state_path=self.state_path,
            control=control,
            probe=probe,
            gateway=gateway,
        )

        with self.assertRaises(self.module.RelayRecoveryError):
            reconciler.reconcile(self.desired)

        self.assertEqual(
            [
                ("forward", 18742, "11.11.10.18", 18731),
                ("cancel", 18742, "11.11.10.18", 18731),
            ],
            control.calls,
        )
        self.assertEqual(("11.11.10.17", 18731), control.targets[18740])


if __name__ == "__main__":
    unittest.main()
