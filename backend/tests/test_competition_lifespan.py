import asyncio
import importlib
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class _FakeCoordinator:
    def __init__(self, tick=None):
        self._tick = tick or (lambda: None)
        self.tick_calls = 0
        self.close_calls = 0
        self.cancel_calls = 0

    def tick_once(self):
        self.tick_calls += 1
        return self._tick()

    def close(self):
        self.close_calls += 1

    def cancel(self, *_args, **_kwargs):
        self.cancel_calls += 1
        raise AssertionError("lifespan must not cancel Slurm work")


class CompetitionLifespanTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.frontend = tempfile.TemporaryDirectory()
        Path(cls.frontend.name, "index.html").write_text("preview", encoding="utf-8")
        cls.environment = patch.dict(
            os.environ,
            {
                "JWT_SECRET": "test-only-competition-lifespan-secret",
                "LMATELAB_FRONTEND_DIST": cls.frontend.name,
            },
        )
        cls.environment.start()
        sys.modules.pop("main_107cup", None)
        cls.main = importlib.import_module("main_107cup")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("main_107cup", None)
        cls.environment.stop()
        cls.frontend.cleanup()

    async def _run_lifespan(self, app, duration=0.04):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(duration)

    async def test_app_construction_does_not_start_coordinator(self):
        coordinator = _FakeCoordinator()
        factory = Mock(return_value=coordinator)

        app = self.main.build_app(
            coordinator_factory=factory,
            coordinator_enabled=True,
            coordinator_interval=0.01,
        )
        await asyncio.sleep(0.02)

        factory.assert_not_called()
        self.assertEqual(0, coordinator.tick_calls)
        self.assertEqual(0, coordinator.close_calls)
        self.assertIsNone(app.state.coordinator_task)

    async def test_disabled_mode_creates_no_coordinator_or_task(self):
        factory = Mock(side_effect=AssertionError("disabled factory must not run"))
        app = self.main.build_app(
            coordinator_factory=factory,
            coordinator_enabled=False,
            coordinator_interval=0.01,
        )

        await self._run_lifespan(app, duration=0.02)

        factory.assert_not_called()
        self.assertIsNone(app.state.coordinator_task)

    async def test_enabled_lifespan_ticks_and_closes_exactly_once(self):
        coordinator = _FakeCoordinator()
        app = self.main.build_app(
            coordinator_factory=lambda: coordinator,
            coordinator_enabled=True,
            coordinator_interval=0.01,
        )

        await self._run_lifespan(app)

        self.assertGreaterEqual(coordinator.tick_calls, 1)
        self.assertEqual(1, coordinator.close_calls)
        self.assertEqual(0, coordinator.cancel_calls)
        self.assertIsNone(app.state.coordinator_task)

    async def test_tick_exceptions_are_sanitized_and_loop_continues(self):
        second_tick = threading.Event()

        def tick():
            if coordinator.tick_calls == 1:
                raise RuntimeError("private scheduler payload")
            second_tick.set()

        coordinator = _FakeCoordinator(tick)
        app = self.main.build_app(
            coordinator_factory=lambda: coordinator,
            coordinator_enabled=True,
            coordinator_interval=0.01,
        )

        with self.assertLogs("main_107cup", level="ERROR") as captured:
            async with app.router.lifespan_context(app):
                reached_second = await asyncio.to_thread(second_tick.wait, 0.5)

        self.assertTrue(reached_second)
        log_text = "\n".join(captured.output)
        self.assertIn("coordinator tick failed", log_text)
        self.assertNotIn("private scheduler payload", log_text)
        self.assertEqual(1, coordinator.close_calls)

    async def test_synchronous_ticks_never_overlap(self):
        lock = threading.Lock()
        state = {"active": 0, "max_active": 0}

        def tick():
            with lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            time.sleep(0.015)
            with lock:
                state["active"] -= 1

        coordinator = _FakeCoordinator(tick)
        app = self.main.build_app(
            coordinator_factory=lambda: coordinator,
            coordinator_enabled=True,
            coordinator_interval=0.005,
        )

        await self._run_lifespan(app, duration=0.06)

        self.assertGreaterEqual(coordinator.tick_calls, 2)
        self.assertEqual(1, state["max_active"])
        self.assertEqual(0, coordinator.cancel_calls)

    def test_loop_uses_elapsed_aware_interval(self):
        self.assertAlmostEqual(
            0.010,
            self.main.coordinator_sleep_seconds(
                interval_seconds=0.025,
                started=10.000,
                finished=10.015,
            ),
        )
        self.assertEqual(
            0.0,
            self.main.coordinator_sleep_seconds(
                interval_seconds=0.025,
                started=10.000,
                finished=10.030,
            ),
        )


class CompetitionProductionCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frontend = tempfile.TemporaryDirectory()
        Path(cls.frontend.name, "index.html").write_text("preview", encoding="utf-8")
        cls.environment = patch.dict(
            os.environ,
            {
                "JWT_SECRET": "test-only-production-coordinator-secret",
                "LMATELAB_FRONTEND_DIST": cls.frontend.name,
            },
        )
        cls.environment.start()
        sys.modules.pop("main_107cup", None)
        cls.main = importlib.import_module("main_107cup")

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("main_107cup", None)
        cls.environment.stop()
        cls.frontend.cleanup()

    def test_production_factory_uses_fixed_runtime_dependencies(self):
        values = {
            "LMATELAB_WORKFLOW_ROOT": "/srv/lmatelab/data/workflows",
            "LMATELAB_SLURM_PROBE_SCRIPT": "/srv/release/probe.slurm",
            "LMATELAB_VASP_STAGE_SCRIPT": "/srv/release/vasp-stage.slurm",
            "LMATELAB_SLURM_USER": "pb23030683",
            "LMATELAB_COORDINATOR_BATCH_LIMIT": "7",
        }
        fake_session_factory = object()
        captured = {}

        class FakeSlurmClient:
            def __init__(self, **kwargs):
                captured["slurm"] = kwargs

        class FakeReconciler:
            def __init__(self, **kwargs):
                captured["reconciler"] = kwargs

        class FakeCoordinator:
            def __init__(self, **kwargs):
                captured["coordinator"] = kwargs

        with (
            patch.object(self.main, "SessionLocal", fake_session_factory),
            patch.object(self.main, "SlurmClient", FakeSlurmClient),
            patch.object(self.main, "CompetitionReconciler", FakeReconciler),
            patch.object(self.main, "CompetitionCoordinator", FakeCoordinator),
        ):
            coordinator = self.main.build_production_coordinator(values)

        self.assertIsInstance(coordinator, FakeCoordinator)
        self.assertEqual(
            {
                "workflow_root": Path(values["LMATELAB_WORKFLOW_ROOT"]),
                "allowed_scripts": (
                    Path(values["LMATELAB_SLURM_PROBE_SCRIPT"]),
                    Path(values["LMATELAB_VASP_STAGE_SCRIPT"]),
                ),
            },
            captured["slurm"],
        )
        self.assertEqual(
            {
                "slurm": captured["reconciler"]["slurm"],
                "probe_script": Path(values["LMATELAB_SLURM_PROBE_SCRIPT"]),
                "vasp_script": Path(values["LMATELAB_VASP_STAGE_SCRIPT"]),
                "slurm_user": "pb23030683",
            },
            captured["reconciler"],
        )
        self.assertEqual(
            fake_session_factory,
            captured["coordinator"]["session_factory"],
        )
        self.assertEqual(
            Path(values["LMATELAB_WORKFLOW_ROOT"]),
            captured["coordinator"]["workflow_root"],
        )
        self.assertEqual(
            Path(values["LMATELAB_VASP_STAGE_SCRIPT"]),
            captured["coordinator"]["vasp_script"],
        )
        self.assertEqual(7, captured["coordinator"]["batch_limit"])


class CompetitionServiceContractTests(unittest.TestCase):
    def test_runtime_environment_examples_are_forced_to_lf(self):
        attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")

        self.assertIn("*.env.example text eol=lf", attributes)

    def test_runtime_example_enables_bounded_coordinator_defaults(self):
        source = (REPO_ROOT / "deploy/107cup/runtime.env.example").read_text(
            encoding="utf-8"
        )
        for required in (
            "LMATELAB_COORDINATOR_ENABLED=1",
            "LMATELAB_COORDINATOR_INTERVAL_SECONDS=10",
            "LMATELAB_COORDINATOR_BATCH_LIMIT=8",
        ):
            self.assertIn(required, source)

    def test_service_pins_coordinator_scripts_to_resolved_release(self):
        source = (REPO_ROOT / "deploy/107cup/service.slurm").read_text(
            encoding="utf-8"
        )
        release_assignment = 'release=$(readlink -f "$root/current")'
        release_export = 'export LMATELAB_RELEASE_ROOT="$release"'
        probe_export = (
            'export LMATELAB_SLURM_PROBE_SCRIPT='
            '"$release/source/deploy/107cup/slurm/probe.slurm"'
        )
        vasp_export = (
            'export LMATELAB_VASP_STAGE_SCRIPT='
            '"$release/source/deploy/107cup/slurm/vasp-stage.slurm"'
        )
        enabled_export = (
            'export LMATELAB_COORDINATOR_ENABLED='
            '"${LMATELAB_COORDINATOR_ENABLED:-1}"'
        )
        for required in (
            release_assignment,
            release_export,
            probe_export,
            vasp_export,
            enabled_export,
        ):
            self.assertIn(required, source)
        self.assertLess(source.index(release_assignment), source.index(vasp_export))
        self.assertNotIn(
            'LMATELAB_VASP_STAGE_SCRIPT="$root/current/',
            source,
        )


if __name__ == "__main__":
    unittest.main()
