import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RECOVERY_SCRIPT = PROJECT_ROOT / "tools" / "ensure_runtime_running.sh"
INSTALLER_SCRIPT = PROJECT_ROOT / "tools" / "install_runtime_recovery_cron.sh"
IMAGE_VALIDATOR = PROJECT_ROOT / "tools" / "verify_backend_image.sh"
RUNTIME_SERVICES = ("redis", "backend", "worker", "beat", "nginx")
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


class RuntimeRecoveryIntegrityTests(unittest.TestCase):
    def setUp(self):
        if not RECOVERY_SCRIPT.is_file() or not INSTALLER_SCRIPT.is_file():
            self.skipTest("required recovery scripts are covered by the existence test")

    def recovery_environment(
        self,
        temp_path: Path,
        *,
        home_ready: bool = True,
        storage_ready: bool = True,
        allowed_users_ready: bool = True,
        backend_image_has_healthcheck: bool = True,
        backend_health: str = "healthy",
        public_https_ok: bool = True,
    ):
        fake_bin = temp_path / "bin"
        fake_bin.mkdir()
        ssl_dir = temp_path / "ssl"
        ssl_dir.mkdir()
        (ssl_dir / "matflow.top.pem").write_text("certificate", encoding="utf-8")
        (ssl_dir / "matflow.top.key").write_text("key", encoding="utf-8")
        backend_env = temp_path / "backend.env"
        backend_env.write_text("TEST_ONLY=1\n", encoding="utf-8")
        data_dir = temp_path / "data"
        data_dir.mkdir()
        if allowed_users_ready:
            (data_dir / "allowed_users.json").write_text("{}\n", encoding="utf-8")

        write_executable(
            fake_bin / "findmnt",
            f"""
            #!/usr/bin/env bash
            case "$*" in
                *" -T /home "*)
                    [[ "{int(home_ready)}" == "1" ]] && printf '%s\\n' '/home nfs4'
                    ;;
                *" -T /storage "*)
                    [[ "{int(storage_ready)}" == "1" ]] && printf '%s\\n' '/storage nfs4'
                    ;;
            esac
            """,
        )
        write_executable(
            fake_bin / "flock",
            """
            #!/usr/bin/env bash
            exit 0
            """,
        )
        write_executable(
            fake_bin / "docker",
            f"""
            #!/usr/bin/env bash
            set -eu
            printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
            case "${{1:-}}" in
                info)
                    exit 0
                    ;;
                compose)
                    case " $* " in
                        *" config --format json "*)
                            printf '%s\\n' '{{"services":{{"backend":{{"build":{{}}}}}}}}'
                            exit 0
                            ;;
                        *" version "*|*" config -q "*|*" up -d redis backend worker beat nginx "*)
                            exit 0
                            ;;
                        *" ps -q "*)
                            printf '%s\\n' "fake-${{@: -1}}-container"
                            exit 0
                            ;;
                        *" ps "*|*" logs "*)
                            exit 0
                            ;;
                    esac
                    ;;
                inspect)
                    case " $* " in
                        *"State.Health.Status"*) printf '%s\\n' '{backend_health}' ;;
                        *) printf '%s\\n' true ;;
                    esac
                    exit 0
                    ;;
                image)
                    [[ "${{@: -1}}" == "lmatelab-backend" ]] && exit 0
                    exit 1
                    ;;
                run)
                    case " $* " in
                        *"run --rm --pull never --entrypoint test lmatelab-backend -f /app/healthcheck.py"*)
                            [[ "{int(backend_image_has_healthcheck)}" == "1" ]] && exit 0
                            exit 1
                            ;;
                    esac
                    exit 99
                    ;;
            esac
            exit 99
            """,
        )
        write_executable(
            fake_bin / "curl",
            f"""
            #!/usr/bin/env bash
            printf '%s\\n' "$*" >> "$FAKE_CURL_LOG"
            case " $* " in
                *" --resolve matflow.top:443:127.0.0.1 "*)
                    printf '%s' 403
                    exit 0
                    ;;
            esac
            [[ "{int(public_https_ok)}" == "1" ]]
            """,
        )
        write_executable(
            fake_bin / "python3",
            """
            #!/usr/bin/env bash
            exec "$FAKE_PYTHON" "$@"
            """,
        )

        docker_log = temp_path / "docker.log"
        curl_log = temp_path / "curl.log"
        bash_env = temp_path / "bash-env"
        bash_env.write_text(
            f'export PATH="{bash_path(fake_bin)}:$PATH"\n', encoding="utf-8"
        )
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
                "LMATELAB_PROJECT_DIR": str(PROJECT_ROOT),
                "LMATELAB_SSL_DIR": str(ssl_dir),
                "LMATELAB_BACKEND_ENV_FILE": str(backend_env),
                "LMATELAB_DATA_DIR": str(data_dir),
                "LMATELAB_RUNTIME_LOCK_FILE": str(temp_path / "recovery.lock"),
                "LMATELAB_RUNTIME_MAX_ATTEMPTS": "1",
                "LMATELAB_RUNTIME_RETRY_DELAY": "0",
                "FAKE_DOCKER_LOG": str(docker_log),
                "FAKE_CURL_LOG": str(curl_log),
                "FAKE_PYTHON": sys.executable,
                "BASH_ENV": bash_path(bash_env),
            }
        )
        return env, docker_log, curl_log

    def run_recovery(self, env):
        return subprocess.run(
            [BASH, str(RECOVERY_SCRIPT)],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_recovery_starts_complete_runtime_and_verifies_health_and_https(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env, docker_log, curl_log = self.recovery_environment(Path(temp_dir))

            result = self.run_recovery(env)

            docker_calls = docker_log.read_text(encoding="utf-8")
            self.assertEqual(
                0, result.returncode, f"{result.stderr}\ndocker calls:\n{docker_calls}"
            )
            self.assertIn("compose -p lmatelab", docker_calls)
            self.assertIn("config -q", docker_calls)
            self.assertIn("up -d redis backend worker beat nginx", docker_calls)
            for service in RUNTIME_SERVICES:
                self.assertIn(f"ps -q {service}", docker_calls)
            self.assertIn(".State.Health.Status", docker_calls)
            curl_calls = curl_log.read_text(encoding="utf-8")
            self.assertIn("--resolve matflow.top:443:127.0.0.1", curl_calls)
            self.assertIn("--write-out %{http_code}", curl_calls)
            self.assertIn("https://matflow.top/", curl_calls)

    def test_recovery_fails_closed_until_both_nfs_mounts_are_ready(self):
        for missing_mount in ("home", "storage"):
            with self.subTest(missing_mount=missing_mount):
                with tempfile.TemporaryDirectory() as temp_dir:
                    env, docker_log, _ = self.recovery_environment(
                        Path(temp_dir),
                        home_ready=missing_mount != "home",
                        storage_ready=missing_mount != "storage",
                    )

                    result = self.run_recovery(env)

                    self.assertNotEqual(0, result.returncode)
                    self.assertIn(f"/{missing_mount}", result.stderr)
                    if docker_log.exists():
                        self.assertNotIn(
                            "up -d redis backend worker beat nginx",
                            docker_log.read_text(encoding="utf-8"),
                        )

    def test_recovery_fails_when_backend_is_not_healthy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env, docker_log, curl_log = self.recovery_environment(
                Path(temp_dir), backend_health="starting"
            )

            result = self.run_recovery(env)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("backend", result.stderr.lower())
            self.assertFalse(curl_log.exists())
            self.assertNotIn(" logs ", f" {docker_log.read_text(encoding='utf-8')} ")

    def test_recovery_fails_before_start_when_backend_image_lacks_healthcheck(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env, docker_log, _ = self.recovery_environment(
                Path(temp_dir), backend_image_has_healthcheck=False
            )

            result = self.run_recovery(env)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("healthcheck.py", result.stderr)
            self.assertNotIn(
                "up -d redis backend worker beat nginx",
                docker_log.read_text(encoding="utf-8"),
            )

    def test_recovery_fails_when_required_runtime_config_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env, docker_log, _ = self.recovery_environment(
                Path(temp_dir), allowed_users_ready=False
            )

            result = self.run_recovery(env)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("allowed_users.json", result.stderr)
            self.assertNotIn(
                "up -d redis backend worker beat nginx",
                docker_log.read_text(encoding="utf-8"),
            )

    def test_recovery_fails_when_public_https_probe_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env, _, _ = self.recovery_environment(
                Path(temp_dir), public_https_ok=False
            )

            result = self.run_recovery(env)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("public HTTPS", result.stderr)

    def test_cron_installer_migrates_legacy_block_idempotently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_crontab = temp_path / "crontab"
            crontab_state = temp_path / "crontab.state"
            crontab_state.write_text(
                textwrap.dedent(
                    """
                    17 2 * * * /home/Pwjb/bin/existing-job
                    # BEGIN LMATELAB NGINX RECOVERY
                    @reboot /bin/bash /home/software/LMateLab/tools/ensure_nginx_running.sh
                    */5 * * * * /bin/bash /home/software/LMateLab/tools/ensure_nginx_running.sh
                    # END LMATELAB NGINX RECOVERY
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            write_executable(
                fake_crontab,
                """
                #!/usr/bin/env bash
                set -eu
                if [[ "${1:-}" == "-l" ]]; then
                    cat "$FAKE_CRONTAB_STATE"
                else
                    cp "$1" "$FAKE_CRONTAB_STATE"
                fi
                """,
            )
            env = os.environ.copy()
            env.update(
                {
                    "LMATELAB_PROJECT_DIR": str(PROJECT_ROOT),
                    "LMATELAB_RUNTIME_LOG_DIR": str(temp_path / "logs"),
                    "LMATELAB_CRONTAB_BIN": str(fake_crontab),
                    "FAKE_CRONTAB_STATE": str(crontab_state),
                }
            )

            first_install = None
            for _ in range(2):
                result = subprocess.run(
                    [BASH, str(INSTALLER_SCRIPT)],
                    cwd=PROJECT_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                if first_install is None:
                    first_install = crontab_state.read_text(encoding="utf-8")

            installed = crontab_state.read_text(encoding="utf-8")
            log_file = temp_path / "logs" / "runtime-recovery.log"
            mode = subprocess.run(
                [BASH, "-c", f"stat -c '%a' '{bash_path(log_file)}'"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(first_install, installed)
            if os.name == "nt":
                installer = INSTALLER_SCRIPT.read_text(encoding="utf-8")
                self.assertIn('chmod 600 "$LOG_FILE"', installer)
            else:
                self.assertEqual("600", mode)
            self.assertIn("17 2 * * * /home/Pwjb/bin/existing-job", installed)
            self.assertNotIn("LMATELAB NGINX RECOVERY", installed)
            self.assertNotIn("ensure_nginx_running.sh", installed)
            self.assertEqual(1, installed.count("# BEGIN LMATELAB RUNTIME RECOVERY"))
            self.assertEqual(1, installed.count("# END LMATELAB RUNTIME RECOVERY"))
            self.assertEqual(1, installed.count("@reboot"))
            self.assertEqual(1, installed.count("*/5 * * * *"))
            self.assertEqual(2, installed.count("umask 077;"))
            self.assertIn("ensure_runtime_running.sh", installed)


class RuntimeRecoveryFilesTests(unittest.TestCase):
    def test_required_recovery_scripts_exist(self):
        self.assertTrue(RECOVERY_SCRIPT.is_file(), str(RECOVERY_SCRIPT))
        self.assertTrue(INSTALLER_SCRIPT.is_file(), str(INSTALLER_SCRIPT))
        self.assertTrue(IMAGE_VALIDATOR.is_file(), str(IMAGE_VALIDATOR))


if __name__ == "__main__":
    unittest.main()
