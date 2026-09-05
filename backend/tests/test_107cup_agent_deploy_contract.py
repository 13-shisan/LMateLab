import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DEPLOY = ROOT / "deploy" / "107cup"


class AgentDeploymentContractTests(unittest.TestCase):
    @staticmethod
    def read(path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def test_agent_dependencies_are_fixed_in_the_107_release(self):
        requirements = self.read(BACKEND / "requirements-107cup.txt").splitlines()
        self.assertIn("pypdf==5.9.0", requirements)
        self.assertIn("qoder-agent-sdk==1.0.14", requirements)

        qoder = self.read(BACKEND / "services" / "qoder_management.py")
        self.assertIn('QODER_SDK_VERSION = "1.0.14"', qoder)
        self.assertIn("PackageNotFoundError", qoder)
        self.assertNotIn('"pip", "install"', qoder)
        self.assertNotIn("subprocess.run(\n                [sys.executable", qoder)

    def test_build_prepares_private_agent_data_and_runs_agent_tests(self):
        source = self.read(DEPLOY / "build.slurm")
        for required in (
            '"$root/data/agent/uploads"',
            '"$root/data/agent/examples/dawn5"',
            '"$root/data/qoder-workspace"',
            '"$root/runtime/qoder"',
            '"$root/config/agent"',
            '"$root/config/secrets"',
            "tests.test_107cup_agent_deploy_contract",
            "tests.test_107cup_agent_deploy_runtime",
            "tests.test_competition_agent_catalog",
            "tests.test_competition_agent_fake_slurm",
            "tests.test_competition_agent_literature",
            "tests.test_competition_agent_migration",
            "tests.test_competition_agent_registration",
            "tests.test_competition_agent_routes",
            "tests.test_competition_agent_runtime",
            "tests.test_competition_agent_security",
            "tests.test_competition_agent_structures",
            "tests.test_competition_agent_tools",
        ):
            self.assertIn(required, source)

    def test_runtime_keeps_agent_writes_under_the_private_107_root(self):
        source = self.read(DEPLOY / "runtime.env.example")
        root = "/home/scc/pb23030683/lmatelab-107cup"
        expected = {
            "LMATELAB_AGENT_UPLOADS_ROOT": f"{root}/data/agent/uploads",
            "LMATELAB_LITERATURE_DB": f"{root}/data/agent/literature.sqlite",
            "LMATELAB_AGENT_EXAMPLES_ROOT": f"{root}/data/agent/examples/dawn5",
            "LMATELAB_AGENT_SETTINGS_FILE": f"{root}/config/agent/settings.json",
            "LMATELAB_LLM_API_KEY_FILE": f"{root}/config/secrets/llm-api-key",
            "LMATELAB_QODER_RUNTIME_DIR": f"{root}/runtime/qoder",
            "LMATELAB_QODER_WORKSPACE_ROOT": f"{root}/data/qoder-workspace",
        }
        values = dict(
            line.split("=", 1)
            for line in source.splitlines()
            if line and not line.startswith("#") and "=" in line
        )
        self.assertEqual("1", values.get("LMATELAB_COMPETITION_AGENT_ENABLED"))
        self.assertEqual("1", values.get("LMATELAB_QODER_MANAGEMENT_ENABLED"))
        for name, value in expected.items():
            self.assertEqual(value, values.get(name), name)

    def test_agent_worker_is_a_long_lived_owned_slurm_service(self):
        worker = self.read(DEPLOY / "agent-worker.slurm")
        control = self.read(DEPLOY / "agent_worker_control.py")
        submit = self.read(DEPLOY / "submit-agent-worker.sh")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-A100",
            "#SBATCH --qos=qos_p107-a100",
            "#SBATCH --time=4-00:00:00",
            'source "$runtime_env"',
            'readlink -f "$root/current"',
            "--poll-seconds 1 --max-idle-cycles 0",
            "agent_worker_control.py\" publish",
            'wait "$worker_pid"',
        ):
            self.assertIn(required, worker)
        for forbidden in ("pip install", "nohup", "QODER_PERSONAL_ACCESS_TOKEN"):
            self.assertNotIn(forbidden, worker)

        for required in (
            "/usr/bin/scontrol",
            "/usr/bin/squeue",
            "/usr/bin/sbatch",
            "agent-worker-state.json",
            "agent-worker-recovery.lock",
            "lmatelab-agent-worker",
            "candidate_ownership_mismatch",
            "multiple_owned_workers",
            "--parsable",
        ):
            self.assertIn(required, control)
        self.assertNotIn("shell=True", control)
        self.assertNotIn("scancel", control)
        self.assertIn('agent_worker_control.py" recover', submit)
        for forbidden in ("python -m services.competition_agent.worker", "pip install", "while true"):
            self.assertNotIn(forbidden, submit)

    def test_worker_supports_zero_as_an_explicit_no_idle_exit_mode(self):
        worker = self.read(BACKEND / "services" / "competition_agent" / "worker.py")
        self.assertIn("not 0 <= args.max_idle_cycles <= 10000", worker)
        self.assertIn("args.max_idle_cycles and idle_cycles >= args.max_idle_cycles", worker)

    def test_service_backs_up_and_validates_databases_around_migrations(self):
        service = self.read(DEPLOY / "service.slurm")
        helper = self.read(DEPLOY / "prepare-databases.py")
        before = service.index('prepare-databases.py" backup')
        migrate = service.index("alembic -c alembic.ini upgrade head")
        after = service.index('prepare-databases.py" verify')
        self.assertLess(before, migrate)
        self.assertLess(migrate, after)
        self.assertIn("sqlite3", helper)
        self.assertIn("integrity_check", helper)
        self.assertIn("source.backup(destination)", helper)
        self.assertIn("os.O_EXCL", helper)

    def test_public_relay_allows_only_exact_operator_agent_writes(self):
        relay = self.read(DEPLOY / "relay" / "nginx.conf.example")
        exact_methods = {
            "/api/competition/agent/qoder/install": "POST",
            "/api/competition/agent/qoder/login": "POST",
            "/api/competition/agent/qoder/service/start": "POST",
            "/api/competition/agent/qoder/service/stop": "POST",
            "/api/competition/agent/settings": "GET PUT",
            "/api/competition/agent/files": "GET POST",
            "/api/competition/agent/literature/index": "POST",
            "/api/competition/agent/structures/build": "POST",
            "/api/competition/agent/structures/bundle": "POST",
            "/api/competition/agent/runs": "GET POST",
        }
        for path, methods in exact_methods.items():
            marker = f"location = {path}"
            self.assertIn(marker, relay)
            location = relay.split(marker, 1)[1].split("location ", 1)[0]
            self.assertIn(f"limit_except {methods}", location)
            self.assertIn("deny all", location)
            self.assertIn("proxy_pass http://127.0.0.1:18740", location)

        uuid_pattern = (
            "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            "[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        )
        patterns = {
            f'^/api/competition/agent/runs/conversations/{uuid_pattern}$': "DELETE",
            f'^/api/competition/agent/runs/{uuid_pattern}/approve$': "POST",
        }
        for pattern, method in patterns.items():
            marker = f'location ~ "{pattern}"'
            self.assertIn(marker, relay)
            location = relay.split(marker, 1)[1].split("location ", 1)[0]
            self.assertIn(f"limit_except {method}", location)
            self.assertIn("deny all", location)

        self.assertIsNone(
            re.search(r"location\s+(?:\^~\s+)?/api/competition/agent/\s*\{", relay)
        )


if __name__ == "__main__":
    unittest.main()
