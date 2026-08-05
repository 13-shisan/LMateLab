import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_ROOT = REPO_ROOT / "deploy" / "107cup"


class CompetitionDeployContractTests(unittest.TestCase):
    def read_required(self, name: str) -> str:
        path = DEPLOY_ROOT / name
        self.assertTrue(path.is_file(), str(path))
        return path.read_text(encoding="utf-8")

    def test_linux_runtime_scripts_are_forced_to_lf_in_git(self):
        attributes_path = REPO_ROOT / ".gitattributes"
        self.assertTrue(attributes_path.is_file(), str(attributes_path))
        attributes = attributes_path.read_text(encoding="utf-8")
        self.assertIn("*.sh text eol=lf", attributes)
        self.assertIn("*.slurm text eol=lf", attributes)

    def test_build_job_runs_only_under_slurm_and_creates_validated_release(self):
        source = self.read_required("build.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "SLURM_JOB_ID",
            "python3 -m venv",
            "requirements-107cup.txt",
            "npm ci",
            "npm run build",
            "VITE_LMATELAB_EDITION=107cup",
            "releases",
            "sha256sum",
            "manifest.sha256",
            "current.next",
            "mv -Tf",
        ):
            self.assertIn(required, source)
        self.assertNotIn("#SBATCH --gres", source)

    def test_service_job_runs_single_uvicorn_and_applies_both_migrations(self):
        source = self.read_required("service.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "alembic -c alembic.ini upgrade head",
            "alembic -c alembic_digest.ini upgrade head",
            "uvicorn main_107cup:app",
            "--workers 1",
            "service-job-id",
            "service-node",
            "service-port",
        ):
            self.assertIn(required, source)
        for forbidden in ("celery worker", "celery beat", "redis-server", "gunicorn"):
            self.assertNotIn(forbidden, source)

    def test_login_node_helpers_only_submit_or_verify(self):
        build_submit = self.read_required("submit-build.sh")
        service_submit = self.read_required("submit-service.sh")
        verifier = self.read_required("verify-runtime.sh")

        self.assertIn("sbatch --parsable", build_submit)
        self.assertIn("sbatch --parsable", service_submit)
        for source in (build_submit, service_submit):
            self.assertNotIn("uvicorn", source)
            self.assertNotIn("npm ", source)
            self.assertNotIn("pip install", source)

        for required in (
            "squeue",
            "sacct",
            "/api/health/live",
            "/api/health/ready",
            "sqlite3",
            "integrity_check",
        ):
            self.assertIn(required, verifier)

    def test_runtime_example_keeps_every_writable_path_under_107_root(self):
        source = self.read_required("runtime.env.example")
        root = "/home/scc/pb23030683/lmatelab-107cup"
        for variable in (
            "LMATELAB_ROOT",
            "DATABASE_URL",
            "DIGEST_DATABASE_URL",
            "LMATELAB_DATA_DIR",
            "UPLOADS_ROOT",
            "ALLOWED_USERS_PATH",
            "SECURITY_POLICY_PATH",
            "ISSUES_DIR",
            "CHANGELOG_PATH",
            "ACADEMIC_REPORTS_FILE",
            "VASP_CUSTOM_DB_ROOT",
            "QE_EPW_CUSTOM_DB_ROOT",
        ):
            line = next((item for item in source.splitlines() if item.startswith(f"{variable}=")), "")
            self.assertTrue(line, variable)
            self.assertIn(root, line, line)

    def test_allowed_users_example_is_fresh_competition_identity(self):
        source = self.read_required("allowed_users.example.json")
        data = json.loads(source)
        self.assertEqual(1, len(data["users"]))
        user = data["users"][0]
        self.assertEqual("107杯管理员", user["nameCN"])
        self.assertEqual("pb23030683", user["aliasEN"])
        self.assertEqual("root", user["role"])
        self.assertTrue(user["enabled"])
        self.assertTrue(user["asedbdir"].startswith("/home/scc/pb23030683/lmatelab-107cup/"))

    def test_security_policy_is_deployable_without_production_config(self):
        source = self.read_required("security_policy.json")
        policy = json.loads(source)["password"]
        self.assertGreaterEqual(policy["minLength"], 10)
        self.assertTrue(policy["requireUpper"])
        self.assertTrue(policy["requireLower"])
        self.assertTrue(policy["allowedPattern"])


if __name__ == "__main__":
    unittest.main()
