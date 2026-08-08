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
            "requirements-107cup.txt",
            "npm ci",
            "npm run build",
            "VITE_LMATELAB_EDITION=107cup",
            "releases",
            "sha256sum",
            "manifest.sha256",
            "current.next",
            "mv -Tf",
            "tests.test_107cup_authz",
        ):
            self.assertIn(required, source)
        self.assertNotIn("#SBATCH --gres", source)

    def test_build_job_uses_module_python_with_a_valid_pip_environment(self):
        source = self.read_required("build.slurm")
        module_init = "source /etc/profile.d/modules.sh"
        module_load = "module load miniconda/py312"
        backups_directory = '"$root/backups"'
        module_python_base = (
            "module_python_base=$(python -c "
            "'import os, sys; print(os.path.realpath(sys.base_prefix))')"
        )
        validation_condition = "\n".join(
            (
                'if ! test -x "$python_env/bin/python" \\',
                '  || ! test "$("$python_env/bin/python" -c '
                "'import os, sys; print(os.path.realpath(sys.base_prefix))')\" "
                '= "$module_python_base" \\',
                '  || ! "$python_env/bin/python" -m pip --version '
                ">/dev/null 2>&1; then",
            )
        )
        backup_recovery = "\n".join(
            (
                '  if test -e "$python_env" || test -L "$python_env"; then',
                '    invalid_python_env="$root/backups/'
                'python-invalid-$SLURM_JOB_ID"',
                '    test ! -e "$invalid_python_env"',
                '    test ! -L "$invalid_python_env"',
                '    mv "$python_env" "$invalid_python_env"',
                "  fi",
                '  python -m venv "$python_env"',
                "fi",
            )
        )
        pip_gate = '"$python_env/bin/python" -m pip --version'
        activation = 'source "$python_env/bin/activate"'
        pip_upgrade = "python -m pip install --upgrade pip"
        requirements_install = (
            'python -m pip install --requirement '
            '"$project/backend/requirements-107cup.txt"'
        )
        postcondition_install = "\n".join(
            (pip_gate, activation, pip_upgrade, requirements_install)
        )

        module_loads = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith("module load ")
        ]
        self.assertEqual([module_load], module_loads)
        for required in (
            module_init,
            backups_directory,
            module_python_base,
            validation_condition,
            backup_recovery,
            postcondition_install,
        ):
            self.assertIn(required, source)

        positions = [
            source.index(module_init),
            source.index(module_load),
            source.index(backups_directory),
            source.index(module_python_base),
            source.index(validation_condition),
            source.index(backup_recovery),
            source.index(postcondition_install),
        ]
        self.assertEqual(sorted(positions), positions)

    def test_service_job_runs_single_uvicorn_and_applies_both_migrations(self):
        source = self.read_required("service.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "#SBATCH --time=4-00:00:00",
            "alembic -c alembic.ini upgrade head",
            "alembic -c alembic_digest.ini upgrade head",
            "uvicorn main_107cup:app",
            "--workers 1",
            "service-job-id",
            "service-node",
            "service-port",
            "migrate-competition-roles.py",
            "--operator-alias",
        ):
            self.assertIn(required, source)
        for forbidden in ("celery worker", "celery beat", "redis-server", "gunicorn"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("#SBATCH --time=7-00:00:00", source)

    def test_rollback_smoke_is_isolated_and_exits_after_self_check(self):
        source = self.read_required("rollback-smoke.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-A100",
            "#SBATCH --qos=qos_p107-a100",
            "#SBATCH --time=00:10:00",
            "LMATELAB_ROLLBACK_RELEASE",
            '[[ "$LMATELAB_ROLLBACK_RELEASE" =~ ^[0-9a-f]{40}$ ]]',
            "umask 077",
            "sha256sum -c manifest.sha256",
            "rollback-current.next",
            "mv -Tf",
            "production_current_before",
            "production_current_after",
            'test "$production_current_before" = "$production_current_after"',
            "DATABASE_URL",
            "DIGEST_DATABASE_URL",
            "alembic -c alembic.ini upgrade head",
            "alembic -c alembic_digest.ini upgrade head",
            "rollback-smoke@example.invalid",
            "rollback-smoke-placeholder",
            "uvicorn main_107cup:app",
            "/api/health/live",
            "/api/health/ready",
            "kill -TERM",
            "wait",
            "set +e",
            "server_status=$?",
            "server-exit-status.txt",
            "Application shutdown complete",
            "Finished server process",
            "integrity_check",
        ):
            self.assertIn(required, source)

        for forbidden in (
            '"$root/current"',
            '"$root/data',
            '"$root/runtime/service-',
            "npm ",
            "pip install",
            "build.slurm",
        ):
            self.assertNotIn(forbidden, source)

        primary_migration = source.index("alembic -c alembic.ini upgrade head")
        synthetic_operator = source.index("rollback-smoke@example.invalid")
        role_migration = source.index("migrate-competition-roles.py")
        self.assertLess(primary_migration, synthetic_operator)
        self.assertLess(synthetic_operator, role_migration)

        controlled_shutdown = source.index('kill -TERM "$server_pid"')
        allow_expected_signal = source.index("set +e", controlled_shutdown)
        wait_for_server = source.index('wait "$server_pid"', allow_expected_signal)
        capture_status = source.index("server_status=$?", wait_for_server)
        restore_errexit = source.index("set -e", capture_status)
        self.assertLess(controlled_shutdown, allow_expected_signal)
        self.assertLess(allow_expected_signal, wait_for_server)
        self.assertLess(wait_for_server, capture_status)
        self.assertLess(capture_status, restore_errexit)

    def test_viewer_provision_job_is_short_private_and_has_no_service_process(self):
        source = self.read_required("provision-viewer.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-A100",
            "#SBATCH --qos=qos_p107-a100",
            "#SBATCH --time=00:05:00",
            "SLURM_JOB_ID",
            "umask 077",
            "demo-viewer.password",
            "demo-viewer@matflow.top",
            "secrets.token_urlsafe",
            "os.O_EXCL",
            "provision-competition-viewer.py",
            "evidence/access",
            "integrity_check",
        ):
            self.assertIn(required, source)
        for forbidden in ("uvicorn", "npm ", "pip install", "celery", "redis-server"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("@lmatelab.invalid", source)

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
        self.assertEqual("operator", user["role"])
        self.assertTrue(user["enabled"])
        self.assertTrue(user["asedbdir"].startswith("/home/scc/pb23030683/lmatelab-107cup/"))

    def test_security_policy_is_deployable_without_production_config(self):
        source = self.read_required("security_policy.json")
        policy = json.loads(source)["password"]
        self.assertGreaterEqual(policy["minLength"], 10)
        self.assertTrue(policy["requireUpper"])
        self.assertTrue(policy["requireLower"])
        self.assertTrue(policy["allowedPattern"])

    def test_competition_runtime_disables_public_account_changes(self):
        source = self.read_required("runtime.env.example")
        self.assertIn("LMATELAB_REGISTRATION_ENABLED=0", source)
        self.assertIn("LMATELAB_PASSWORD_RESET_ENABLED=0", source)

    def test_public_relay_allows_login_but_rejects_business_writes(self):
        relay = self.read_required("relay/nginx.conf.example")
        self.assertIn("listen 18733", relay)
        self.assertIn("client_body_temp_path /home/Pwjb/.config/lmatelab-107cup-proxy/client-body", relay)
        self.assertIn("proxy_temp_path /home/Pwjb/.config/lmatelab-107cup-proxy/proxy-temp", relay)
        self.assertIn("proxy_http_version 1.1", relay)
        self.assertIn("proxy_buffering off", relay)
        self.assertIn("location = /api/auth/login", relay)
        self.assertIn("limit_except POST", relay)
        self.assertIn("location /api/", relay)
        self.assertIn("limit_except GET", relay)
        self.assertIn("deny all", relay)
        self.assertIn("allow 114.214.203.210", relay)
        self.assertIn("proxy_pass http://127.0.0.1:18734", relay)


if __name__ == "__main__":
    unittest.main()
