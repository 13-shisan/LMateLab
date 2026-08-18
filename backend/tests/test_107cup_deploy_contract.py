import ast
import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace


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

    def test_stage6_probe_is_fixed_small_private_and_never_runs_vasp(self):
        source = self.read_required("slurm/probe.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "#SBATCH --nodes=1",
            "#SBATCH --ntasks=1",
            "#SBATCH --cpus-per-task=1",
            "#SBATCH --mem=256M",
            "#SBATCH --time=00:03:00",
            "SLURM_JOB_ID",
            "umask 077",
            "success|fail|cancel",
            "exit 42",
            "sleep 1",
        ):
            self.assertIn(required, source)
        for forbidden in ("vasp", "mpirun", "srun", "eval", "bash -c", "sh -c"):
            self.assertNotIn(forbidden, source.lower())

    def test_stage6_smoke_is_compute_only_isolated_and_hashes_all_evidence(self):
        source = self.read_required("slurm/stage6-smoke.py")
        for required in (
            "SLURM_JOB_ID",
            "sqlite:///",
            "stage6-smoke.sqlite",
            "CompetitionReconciler",
            "SlurmClient",
            "success",
            "fail",
            "cancel",
            "submission_accepted",
            "submission_failed",
            "cancellation_requested",
            "scheduler_state_changed",
            "manifest.sha256",
            "hashlib.sha256",
            "integrity_check",
        ):
            self.assertIn(required, source)
        for forbidden in ("shell=True", "docker", "vasp_std", "vasp_gam", "vasp_ncl"):
            self.assertNotIn(forbidden, source)

    def test_stage6_smoke_test_only_probe_uses_typed_probe_runner(self):
        source = self.read_required("slurm/stage6-smoke.py")
        module = ast.parse(source)
        function = next(
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "test_only_probe"
        )

        class TypedSubmission:
            created: list["TypedSubmission"] = []

            def __init__(
                self,
                *,
                workflow_id: str,
                attempt_id: str,
                step_key: str,
                attempt_number: int,
                attempt_directory: Path,
                script_path: Path,
                runner_kind: str,
                runner_mode: str,
            ) -> None:
                self.runner_kind = runner_kind
                self.runner_mode = runner_mode
                self.job_name = "typed-probe-job"
                self.__class__.created.append(self)

        class Client:
            def prepare_attempt_directory(self, workflow_id: str, attempt_id: str) -> Path:
                return Path("/attempts") / workflow_id / attempt_id

            def test_submission(self, submission: TypedSubmission) -> SimpleNamespace:
                return SimpleNamespace(returncode=0, stderr="", stdout="")

        namespace = {
            "PROBE_SCRIPT": Path("/fixed/probe.slurm"),
            "SlurmSubmission": TypedSubmission,
            "create_client": lambda: Client(),
            "hashlib": hashlib,
            "json": json,
            "run_command": lambda *_args, **_kwargs: {"stdout": '{"jobs": []}'},
            "uuid": SimpleNamespace(uuid4=lambda: "00000000-0000-4000-8000-000000000001"),
        }
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "stage6-smoke.py", "exec"),
            namespace,
        )

        result = namespace["test_only_probe"]()

        self.assertEqual(0, result["returncode"])
        self.assertEqual(1, len(TypedSubmission.created))
        self.assertEqual(
            ("probe", "success"),
            (TypedSubmission.created[0].runner_kind, TypedSubmission.created[0].runner_mode),
        )

    def test_stage6_smoke_resolves_the_pinned_release_when_slurm_spools_the_script(self):
        source = self.read_required("slurm/stage6-smoke.py")

        self.assertNotIn("Path(__file__).resolve()", source)
        for required in (
            'RELEASE_COMMIT = os.environ.get("LMATELAB_GIT_COMMIT", "")',
            'RELEASE_PARENT = Path("/home/scc/pb23030683/lmatelab-107cup/releases")',
            'RELEASE_ROOT = RELEASE_PARENT / RELEASE_COMMIT',
            'BACKEND_ROOT = RELEASE_ROOT / "source" / "backend"',
            'os.environ["LMATELAB_SLURM_PROBE_SCRIPT"] = str(',
            'EVIDENCE_ROOT.mkdir(mode=0o700, parents=True)',
            'EVIDENCE_ROOT / "failure.json"',
        ):
            self.assertIn(required, source)

        evidence_creation = source.index("EVIDENCE_ROOT.mkdir(mode=0o700, parents=True)")
        backend_validation = source.index("competition backend source is unavailable")
        sqlalchemy_import = source.index("from sqlalchemy import")
        self.assertLess(evidence_creation, backend_validation)
        self.assertLess(evidence_creation, sqlalchemy_import)

    def test_formal_build_runs_stage5_and_stage6_workflow_suites(self):
        source = self.read_required("build.slurm")
        for suite in (
            "tests.test_competition_workflow_models",
            "tests.test_competition_inputs",
            "tests.test_competition_workflow_service",
            "tests.test_competition_workflow_routes",
            "tests.test_competition_slurm",
            "tests.test_competition_slurm_linux",
        ):
            self.assertIn(suite, source)

    def test_formal_release_materializes_the_fixed_stage6_script_path(self):
        source = self.read_required("build.slurm")
        self.assertIn('"$staging/deploy/107cup"', source)
        self.assertIn(
            'cp -a "$project/deploy/107cup/slurm" "$staging/deploy/107cup/"',
            source,
        )
        self.assertIn("find source frontend-dist deploy -type f", source)

    def test_stage7_vasp_runner_has_only_fixed_resources_identity_and_commands(self):
        source = self.read_required("slurm/vasp-stage.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "#SBATCH --nodes=1",
            "#SBATCH --ntasks=1",
            "#SBATCH --cpus-per-task=16",
            "#SBATCH --gres=gpu:RTX5090:1",
            "#SBATCH --mem=32G",
            "#SBATCH --time=06:00:00",
            'test "$#" -eq 3',
            "case \"$stage\" in relax|scf|band|dos)",
            "^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            'test "$PWD" = "$LMATELAB_WORKFLOW_ROOT/$workflow_id/attempts/$attempt_id"',
            "test \"$(<POTCAR.spec)\" = $'Mo_sv\\nS'",
            "2731df97e41766cc617548c5a8267718fdef1f509ac6bafa01e745abea2bdfaa",
            "0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132",
            "509d41b6c93c3d7495d976f7a04dcf3f6960cfc94f39f13a67d146a7ded33045",
            "PAW_PBE\\ Mo_sv*",
            "PAW_PBE\\ S\\ *",
            "/home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit -task 103",
            "/home/scc/pb23030683/software/vasp.6.4.2-GPU-Cell/env-nvhpc.sh",
            "/usr/bin/time -v -o runtime-time.txt",
            'mpirun --bind-to none -np "$SLURM_NTASKS" vasp_std',
            "umask 077",
        ):
            self.assertIn(required, source)
        for forbidden in ("eval ", "bash -c", "sh -c", "docker", "singularity", "srun --pty"):
            self.assertNotIn(forbidden, source)

    def test_stage7_vasp_runner_preserves_common_evidence_and_vasp_exit_status(self):
        source = self.read_required("slurm/vasp-stage.slurm")
        for evidence_name in (
            "POTCAR",
            "potcar-source-sha256.txt",
            "vaspkit-version.txt",
            "vasp-exit-code.txt",
            "runtime-time.txt",
        ):
            self.assertIn(evidence_name, source)

        allow_nonzero = source.index("set +e")
        execute_vasp = source.index("/usr/bin/time -v -o runtime-time.txt", allow_nonzero)
        capture_status = source.index("vasp_status=$?", execute_vasp)
        restore_errexit = source.index("set -e", capture_status)
        write_status = source.index('> vasp-exit-code.txt', restore_errexit)
        preserve_status = source.index('exit "$vasp_status"', write_status)
        self.assertLess(allow_nonzero, execute_vasp)
        self.assertLess(execute_vasp, capture_status)
        self.assertLess(capture_status, restore_errexit)
        self.assertLess(restore_errexit, write_status)
        self.assertLess(write_status, preserve_status)

    def test_stage7_preflight_is_short_private_fixed_and_never_executes_vasp(self):
        source = self.read_required("slurm/stage7-preflight.slurm")
        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "#SBATCH --time=00:05:00",
            "SLURM_JOB_ID",
            "umask 077",
            'evidence/stage7/preflight-$SLURM_JOB_ID',
            "competition_templates/mos2_v1",
            '"$template/POSCAR"',
            "POTCAR.spec",
            "vaspkit -task 103",
            "2731df97e41766cc617548c5a8267718fdef1f509ac6bafa01e745abea2bdfaa",
            "0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132",
            "509d41b6c93c3d7495d976f7a04dcf3f6960cfc94f39f13a67d146a7ded33045",
            "PAW_PBE\\ Mo_sv*",
            "PAW_PBE\\ S\\ *",
            "env-nvhpc.sh",
            "command -v vasp_std",
            'ldd "$(command -v vasp_std)"',
        ):
            self.assertIn(required, source)
        for forbidden in ("mpirun", "/usr/bin/time", "srun "):
            self.assertNotIn(forbidden, source)

    def test_stage7_internal_acceptance_creator_is_fixed_short_and_nonpublic(self):
        python_source = self.read_required("slurm/stage7-acceptance.py")
        slurm_source = self.read_required("slurm/stage7-acceptance.slurm")
        for required in (
            'parser.add_argument("--profile", choices=("scf_nonconvergence_v1",), required=True)',
            'parser.add_argument("--operator-alias", default="pb23030683")',
            "DraftCreateRequest",
            "create_draft",
            "confirm_workflow",
            "render_acceptance_scf_incar",
            'logical_path == "scf/INCAR"',
            "hashlib.sha256(rendered).hexdigest()",
            'metadata["input_manifest"]',
            "run.input_sha256",
            'event_type="acceptance_profile_configured"',
            '"profile": "scf_nonconvergence_v1"',
            "build_production_coordinator",
            "coordinator.start",
        ):
            self.assertIn(required, python_source)
        for forbidden in (
            "shell=True",
            "subprocess",
            "os.system",
            "/home/scc/pb23030683/POTCAR",
            "TITEL  =",
        ):
            self.assertNotIn(forbidden, python_source)

        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-RTX5090",
            "#SBATCH --qos=qos_p107-rtx5090",
            "#SBATCH --time=00:05:00",
            "SLURM_JOB_ID",
            "runtime.env",
            "envs/python",
            "stage7-acceptance.py",
            "--profile scf_nonconvergence_v1",
        ):
            self.assertIn(required, slurm_source)
        for forbidden in ("vasp_std", "vasp_gam", "vasp_ncl", "mpirun", "vaspkit"):
            self.assertNotIn(forbidden, slurm_source.lower())

    def test_formal_build_runs_stage7_backend_suites(self):
        source = self.read_required("build.slurm")
        for suite in (
            "tests.test_competition_attempt_inputs",
            "tests.test_competition_vasp",
            "tests.test_competition_coordinator",
            "tests.test_competition_lifespan",
        ):
            self.assertIn(suite, source)

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
        self.assertIn("LMATELAB_SLURM_USER=pb23030683", source)
        self.assertIn(
            "LMATELAB_SLURM_PROBE_SCRIPT=/home/scc/pb23030683/lmatelab-107cup/current/deploy/107cup/slurm/probe.slurm",
            source,
        )

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
