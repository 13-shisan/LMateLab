import importlib
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class CompetitionRuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module_path = BACKEND_ROOT / "competition_runtime.py"
        cls.runtime = None
        if cls.module_path.is_file():
            cls.runtime = importlib.import_module("competition_runtime")

    def require_runtime(self):
        if self.runtime is None:
            self.skipTest("competition_runtime.py is not implemented yet")
        return self.runtime

    def test_competition_runtime_module_exists(self):
        self.assertTrue(self.module_path.is_file(), str(self.module_path))

    def test_deployment_metadata_contains_only_traceable_runtime_fields(self):
        runtime = self.require_runtime()
        environ = {
            "SLURM_JOB_ID": "32599",
            "SLURMD_NODENAME": "anode16",
            "LMATELAB_GIT_COMMIT": "abc1234",
            "LMATELAB_MANIFEST_SHA256": "def5678",
            "LMATELAB_STARTED_AT": "2026-08-05T12:00:00+08:00",
            "LMATELAB_RELEASE_KIND": "preview",
            "LMATELAB_DATA_MODE": "demo",
            "JWT_SECRET": "must-not-leak",
        }

        self.assertEqual(
            {
                "job_id": "32599",
                "node": "anode16",
                "commit": "abc1234",
                "manifest_sha256": "def5678",
                "started_at": "2026-08-05T12:00:00+08:00",
                "release_kind": "preview",
                "data_mode": "demo",
            },
            runtime.deployment_metadata(environ),
        )

    def test_deployment_metadata_defaults_to_stable_live_without_secrets(self):
        runtime = self.require_runtime()
        metadata = runtime.deployment_metadata({"JWT_SECRET": "must-not-leak"})

        self.assertEqual("stable", metadata["release_kind"])
        self.assertEqual("live", metadata["data_mode"])
        self.assertNotIn("JWT_SECRET", metadata)
        self.assertNotIn("jwt_secret", metadata)

    def test_spa_resolver_serves_assets_and_falls_back_to_index(self):
        runtime = self.require_runtime()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index = root / "index.html"
            asset = root / "assets" / "app.js"
            asset.parent.mkdir()
            index.write_text("index", encoding="utf-8")
            asset.write_text("asset", encoding="utf-8")

            self.assertEqual(asset, runtime.resolve_frontend_file(root, "assets/app.js"))
            self.assertEqual(index, runtime.resolve_frontend_file(root, "dashboard"))

    def test_spa_resolver_rejects_api_fallback_and_path_escape(self):
        runtime = self.require_runtime()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text("index", encoding="utf-8")

            with self.assertRaises(LookupError):
                runtime.resolve_frontend_file(root, "api/missing")
            with self.assertRaises(ValueError):
                runtime.resolve_frontend_file(root, "../outside.txt")

    def test_router_allowlist_excludes_undeployed_modules(self):
        runtime = self.require_runtime()
        modules = {module_name for module_name, _router_name in runtime.CORE_ROUTER_IMPORTS}

        self.assertIn(("auth", "competition_router"), runtime.CORE_ROUTER_IMPORTS)

        self.assertEqual(
            {
                "auth",
                "routers.health",
            },
            modules,
        )
        for disabled in (
            "projects",
            "notes",
            "files",
            "vasp_db",
            "changelog",
            "issues",
            "academic_reports",
            "agents",
            "papers",
            "qe_epw",
            "server_monitor",
            "dailypapers",
        ):
            self.assertFalse(any(disabled in module_name for module_name in modules))

    def test_workflow_router_is_the_only_business_router(self):
        runtime = self.require_runtime()

        self.assertEqual(
            (("routers.competition_workflows", "router"),),
            runtime.BUSINESS_ROUTER_IMPORTS,
        )

    def test_workflow_root_is_environment_driven_with_107_writable_default(self):
        runtime = self.require_runtime()

        configured = runtime.workflow_root(
            {"LMATELAB_WORKFLOW_ROOT": "/tmp/lmatelab-stage5"}
        )
        default = runtime.workflow_root({})

        self.assertEqual(Path("/tmp/lmatelab-stage5"), configured)
        self.assertEqual(
            Path("/home/scc/pb23030683/lmatelab-107cup/data/workflows"),
            default,
        )

    def test_release_commit_requires_full_lowercase_git_sha(self):
        runtime = self.require_runtime()

        self.assertEqual("a" * 40, runtime.release_commit({"LMATELAB_GIT_COMMIT": "a" * 40}))
        for values in ({}, {"LMATELAB_GIT_COMMIT": "unknown"}, {"LMATELAB_GIT_COMMIT": "A" * 40}):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    runtime.release_commit(values)

    def test_slurm_identity_and_probe_path_are_fixed_by_runtime_configuration(self):
        runtime = self.require_runtime()
        probe = "/opt/lmatelab/deploy/107cup/slurm/probe.slurm"

        self.assertEqual(
            "pb23030683",
            runtime.slurm_user({"LMATELAB_SLURM_USER": "pb23030683"}),
        )
        self.assertEqual(
            Path(probe),
            runtime.slurm_probe_script({"LMATELAB_SLURM_PROBE_SCRIPT": probe}),
        )
        for values in (
            {"LMATELAB_SLURM_USER": "bad user"},
            {"LMATELAB_SLURM_PROBE_SCRIPT": "relative/probe.slurm"},
            {"LMATELAB_SLURM_PROBE_SCRIPT": "/opt/../tmp/probe.slurm"},
        ):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    if "LMATELAB_SLURM_USER" in values:
                        runtime.slurm_user(values)
                    else:
                        runtime.slurm_probe_script(values)

    def test_vasp_coordinator_runtime_configuration_is_strict(self):
        runtime = self.require_runtime()
        values = {
            "LMATELAB_VASP_STAGE_SCRIPT": "/opt/lmatelab/vasp-stage.slurm",
            "LMATELAB_COORDINATOR_ENABLED": "1",
            "LMATELAB_COORDINATOR_INTERVAL_SECONDS": "10",
            "LMATELAB_COORDINATOR_BATCH_LIMIT": "8",
            "LMATELAB_COORDINATOR_DRAIN_TIMEOUT_SECONDS": "10",
        }

        self.assertEqual(
            Path(values["LMATELAB_VASP_STAGE_SCRIPT"]),
            runtime.vasp_stage_script(values),
        )
        self.assertTrue(runtime.coordinator_enabled(values))
        self.assertEqual(10.0, runtime.coordinator_interval_seconds(values))
        self.assertEqual(8, runtime.coordinator_batch_limit(values))
        self.assertEqual(10.0, runtime.coordinator_drain_timeout_seconds(values))

    def test_vasp_coordinator_runtime_configuration_has_bounded_defaults(self):
        runtime = self.require_runtime()

        self.assertTrue(runtime.coordinator_enabled({}))
        self.assertEqual(10.0, runtime.coordinator_interval_seconds({}))
        self.assertEqual(8, runtime.coordinator_batch_limit({}))
        self.assertEqual(10.0, runtime.coordinator_drain_timeout_seconds({}))

    def test_vasp_stage_script_rejects_relative_and_traversing_paths(self):
        runtime = self.require_runtime()

        for value in (
            "relative/vasp-stage.slurm",
            "/opt/lmatelab/../vasp-stage.slurm",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    runtime.vasp_stage_script({"LMATELAB_VASP_STAGE_SCRIPT": value})

    def test_coordinator_enabled_accepts_only_exact_zero_or_one(self):
        runtime = self.require_runtime()

        self.assertFalse(
            runtime.coordinator_enabled({"LMATELAB_COORDINATOR_ENABLED": "0"})
        )
        for value in ("true", "false", "yes", "2", " 1", "1 ", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    runtime.coordinator_enabled(
                        {"LMATELAB_COORDINATOR_ENABLED": value}
                    )

    def test_coordinator_interval_rejects_malformed_nonfinite_and_out_of_range(self):
        runtime = self.require_runtime()

        for value in (
            "invalid",
            str(math.nan),
            str(math.inf),
            str(-math.inf),
            " 10",
            "1.999",
            "60.001",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    runtime.coordinator_interval_seconds(
                        {"LMATELAB_COORDINATOR_INTERVAL_SECONDS": value}
                    )

    def test_coordinator_batch_rejects_malformed_and_out_of_range(self):
        runtime = self.require_runtime()

        for value in ("invalid", "1.0", "0", "33", " 8", "08"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    runtime.coordinator_batch_limit(
                        {"LMATELAB_COORDINATOR_BATCH_LIMIT": value}
                    )

    def test_coordinator_drain_timeout_is_finite_and_bounded(self):
        runtime = self.require_runtime()

        self.assertEqual(
            0.05,
            runtime.coordinator_drain_timeout_seconds(
                {"LMATELAB_COORDINATOR_DRAIN_TIMEOUT_SECONDS": "0.05"}
            ),
        )
        for value in ("invalid", "nan", "inf", " 0.05", "0.009", "60.001"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    runtime.coordinator_drain_timeout_seconds(
                        {"LMATELAB_COORDINATOR_DRAIN_TIMEOUT_SECONDS": value}
                    )

    def test_main_entrypoint_integrates_router_allowlist_and_spa_resolver(self):
        entrypoint = BACKEND_ROOT / "main_107cup.py"
        self.assertTrue(entrypoint.is_file(), str(entrypoint))

        source = entrypoint.read_text(encoding="utf-8")
        self.assertIn("CORE_ROUTER_IMPORTS", source)
        self.assertIn("resolve_frontend_file", source)
        self.assertIn("assert_unique_routes", source)
        self.assertIn('APIRouter(prefix="/api")', source)
        self.assertIn("require_business_access", source)

    def test_sqlite_connection_pragmas_are_nfs_friendly(self):
        runtime = self.require_runtime()
        self.assertTrue(
            hasattr(runtime, "SQLITE_CONNECTION_PRAGMAS"),
            "competition_runtime.SQLITE_CONNECTION_PRAGMAS is missing",
        )
        if not hasattr(runtime, "SQLITE_CONNECTION_PRAGMAS"):
            return
        self.assertEqual(
            (
                "PRAGMA foreign_keys=ON;",
                "PRAGMA journal_mode=DELETE;",
                "PRAGMA synchronous=NORMAL;",
                "PRAGMA busy_timeout=5000;",
            ),
            runtime.SQLITE_CONNECTION_PRAGMAS,
        )

        source = (BACKEND_ROOT / "database.py").read_text(encoding="utf-8")
        self.assertIn("SQLITE_CONNECTION_PRAGMAS", source)

    def test_runtime_config_paths_are_environment_driven(self):
        auth_source = (BACKEND_ROOT / "auth.py").read_text(encoding="utf-8")
        authz_source = (BACKEND_ROOT / "authz_db.py").read_text(encoding="utf-8")

        self.assertIn('os.getenv("ALLOWED_USERS_PATH"', auth_source)
        for variable in (
            "ALLOWED_USERS_PATH",
            "UPLOADS_ROOT",
            "VASP_CUSTOM_DB_ROOT",
            "QE_EPW_CUSTOM_DB_ROOT",
        ):
            self.assertIn(f'os.getenv("{variable}"', authz_source)

    def test_competition_requirements_exclude_unbounded_ml_runtimes(self):
        requirements = BACKEND_ROOT / "requirements-107cup.txt"
        self.assertTrue(requirements.is_file(), str(requirements))
        packages = {
            line.split("==", 1)[0].strip().lower()
            for line in requirements.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        for excluded in (
            "torch",
            "transformers",
            "sentence-transformers",
            "chromadb",
            "mineru",
            "flagembedding",
        ):
            self.assertNotIn(excluded, packages)
        for required in (
            "fastapi",
            "uvicorn",
            "sqlalchemy",
            "alembic",
            "ase",
            "httpx",
            "pypdf",
            "qoder-agent-sdk",
        ):
            self.assertIn(required, packages)


if __name__ == "__main__":
    unittest.main()
