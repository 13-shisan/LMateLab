import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = PROJECT_ROOT / "tools" / "deploy_backend_safely.sh"
BUILD_TRANSACTION = PROJECT_ROOT / "tools" / "build_python_images_safely.sh"
CANONICAL_ROOT = Path(
    os.getenv("LMATELAB_PROJECT_DIR", "/home/software/LMateLab")
).resolve()
WINDOWS_GIT_BASH = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
BASH = str(WINDOWS_GIT_BASH) if WINDOWS_GIT_BASH.is_file() else shutil.which("bash")


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def bash_path(path: Path) -> str:
    resolved = path.resolve().as_posix()
    if os.name == "nt":
        return f"/{resolved[0].lower()}{resolved[2:]}"
    return resolved


class DeployScriptIntegrityTests(unittest.TestCase):
    def test_deploy_script_only_accepts_canonical_production_checkout(self):
        result = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), "--check-root-only"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )

        if PROJECT_ROOT.resolve() == CANONICAL_ROOT:
            self.assertEqual(0, result.returncode, result.stderr)
        else:
            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "must run from canonical production checkout",
                result.stderr,
            )

    def test_public_probe_verifies_tls_certificate(self):
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("https://matflow.top", script)
        self.assertNotIn("curl -k", script)

    def test_deployment_prewarms_server_monitor_overview_ranges(self):
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("refresh_users_overview_cache", script)
        self.assertIn("(7, 30, 90, 365)", script)

    def test_deployment_validates_new_and_rollback_backend_images_before_recreate(self):
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

        rollback_build = script.index("docker build --pull=false")
        rollback_validate = script.index(
            '/bin/bash "$IMAGE_VALIDATOR" "$rollback_tag"', rollback_build
        )
        build_transaction = script.index(
            '/bin/bash "$BUILD_TRANSACTION" "${ROLLBACK_IMAGE_ARGS[@]}"',
            rollback_validate,
        )
        deployment_starts = script.index("DEPLOY_STARTED=1")
        first_recreate = script.index('up -d --no-deps --force-recreate', deployment_starts)

        self.assertLess(rollback_build, rollback_validate)
        self.assertLess(rollback_validate, build_transaction)
        self.assertLess(build_transaction, deployment_starts)
        self.assertLess(deployment_starts, first_recreate)
        self.assertIn("--pull=false", script)
        self.assertIn("ROLLBACK_IMAGES[backend]", script)
        self.assertIn('--restore-only "${ROLLBACK_IMAGE_ARGS[@]}"', script)


class ImageBuildTransactionTests(unittest.TestCase):
    def run_transaction(
        self,
        temp_path: Path,
        *,
        build_status: int = 0,
        validation_status: int = 0,
        tag_failure_service: str = "",
    ):
        fake_bin = temp_path / "bin"
        fake_bin.mkdir()
        docker_log = temp_path / "docker.log"
        validator = temp_path / "validator"
        bash_env = temp_path / "bash-env"
        write_executable(
            fake_bin / "docker",
            """
            #!/usr/bin/env bash
            set -eu
            printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
            if [[ "${1:-}" == "compose" && " $* " == *" build backend worker beat "* ]]; then
                exit "$FAKE_BUILD_STATUS"
            fi
            if [[ "${1:-}" == "image" && "${2:-}" == "tag" ]]; then
                service="${4#lmatelab-}"
                service="${service%:latest}"
                [[ -z "$FAKE_TAG_FAILURE_SERVICE" || "$service" != "$FAKE_TAG_FAILURE_SERVICE" ]]
                exit
            fi
            exit 99
            """,
        )
        write_executable(
            validator,
            """
            #!/usr/bin/env bash
            exit "$FAKE_VALIDATION_STATUS"
            """,
        )
        bash_env.write_text(
            f'export PATH="{bash_path(fake_bin)}:$PATH"\n', encoding="utf-8"
        )
        env = os.environ.copy()
        env.update(
            {
                "BASH_ENV": bash_path(bash_env),
                "FAKE_BUILD_STATUS": str(build_status),
                "FAKE_DOCKER_LOG": str(docker_log),
                "FAKE_TAG_FAILURE_SERVICE": tag_failure_service,
                "FAKE_VALIDATION_STATUS": str(validation_status),
                "LMATELAB_IMAGE_VALIDATOR": str(validator),
                "LMATELAB_PROJECT_DIR": str(PROJECT_ROOT),
            }
        )
        result = subprocess.run(
            [
                BASH,
                str(BUILD_TRANSACTION),
                "backend=old-backend",
                "worker=old-worker",
                "beat=old-beat",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        calls = docker_log.read_text(encoding="utf-8") if docker_log.exists() else ""
        return result, calls

    def assert_all_canonical_tags_restored_without_recreate(self, calls: str):
        for service in ("backend", "worker", "beat"):
            self.assertIn(
                f"image tag old-{service} lmatelab-{service}:latest", calls
            )
        self.assertNotIn("up -d", calls)
        self.assertNotIn("force-recreate", calls)

    def test_build_and_validation_failures_restore_tags_without_recreate(self):
        scenarios = ((19, 0, 19), (0, 23, 23))
        for build_status, validation_status, expected_status in scenarios:
            with self.subTest(
                build_status=build_status, validation_status=validation_status
            ):
                with tempfile.TemporaryDirectory() as temp_dir:
                    result, calls = self.run_transaction(
                        Path(temp_dir),
                        build_status=build_status,
                        validation_status=validation_status,
                    )

                    self.assertEqual(expected_status, result.returncode, result.stderr)
                    self.assert_all_canonical_tags_restored_without_recreate(calls)

    def test_tag_restore_failure_uses_critical_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result, _ = self.run_transaction(
                Path(temp_dir), build_status=19, tag_failure_service="worker"
            )

            self.assertEqual(70, result.returncode, result.stderr)
            self.assertIn("CRITICAL", result.stderr)

    def test_build_transaction_helper_exists(self):
        self.assertTrue(BUILD_TRANSACTION.is_file(), str(BUILD_TRANSACTION))


if __name__ == "__main__":
    unittest.main()
