from __future__ import annotations

import importlib.util
from importlib.metadata import PackageNotFoundError, version
import json
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


QODERCN_SDK_VERSION = "1.0.14"
QODERCN_LOGIN_HOSTS = frozenset({"qoder.cn", "qoder.com.cn"})
_LOGIN_LOCK = threading.Lock()
_LOGIN_PROCESS: subprocess.Popen[str] | None = None
_LOGIN_URL: str | None = None
_LOGIN_ERROR: str | None = None


class QoderManagementError(RuntimeError):
    pass


def management_enabled() -> bool:
    return os.environ.get("LMATELAB_QODER_MANAGEMENT_ENABLED", "0") == "1"


def _require_enabled() -> None:
    if not management_enabled():
        raise QoderManagementError("Qoder management is disabled")


def _runtime_dir() -> Path:
    path = Path(os.environ.get("LMATELAB_QODER_RUNTIME_DIR", "/tmp/lmatelab-qoder"))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _workspace_dir() -> Path:
    path = Path(os.environ.get("LMATELAB_QODER_WORKSPACE_ROOT", "/tmp/lmatelab-qoder-workspace"))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _qodercn_env() -> dict[str, str]:
    values = os.environ.copy()
    config_dir = Path(
        values.get("QODERCN_CONFIG_DIR") or (_runtime_dir() / "config")
    )
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_dir.chmod(0o700)
    values["QODERCN_CONFIG_DIR"] = str(config_dir)
    return values


def _cli_path() -> Path | None:
    spec = importlib.util.find_spec("qodercn_agent_sdk")
    if spec is None or spec.origin is None:
        return None
    candidate = Path(spec.origin).resolve().parent / "_bundled" / "qoderclicn"
    return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None


def _service_pid() -> int | None:
    path = _runtime_dir() / "remote-control.pid"
    try:
        pid = int(path.read_text(encoding="ascii").strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return None


def _account_status(cli: Path) -> dict[str, object]:
    try:
        result = subprocess.run(
            [str(cli), "status", "-o", "json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
            env=_qodercn_env(),
        )
        value = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        value = {}
    return {
        "authenticated": value.get("logged_in") is True,
        "version": str(value.get("version") or "") or None,
        "username": str(value.get("username") or "")[:120] or None,
    }


def qoder_status() -> dict[str, object]:
    cli = _cli_path()
    account = _account_status(cli) if cli else {
        "authenticated": False,
        "version": None,
        "username": None,
    }
    with _LOGIN_LOCK:
        login_pending = _LOGIN_PROCESS is not None and _LOGIN_PROCESS.poll() is None
        login_url = _LOGIN_URL if login_pending else None
        login_error = _LOGIN_ERROR
    return {
        "manageable": management_enabled(),
        "installed": cli is not None,
        **account,
        "service_running": _service_pid() is not None,
        "login_pending": login_pending,
        "login_url": login_url,
        "last_error": login_error,
    }


def install_qoder() -> dict[str, object]:
    _require_enabled()
    try:
        installed_version = version("qodercn-agent-sdk")
    except PackageNotFoundError as exc:
        raise QoderManagementError("Qoder is not installed in this release") from exc
    if installed_version != QODERCN_SDK_VERSION:
        raise QoderManagementError(
            f"Qoder CN release version mismatch: expected {QODERCN_SDK_VERSION}"
        )
    if _cli_path() is None:
        raise QoderManagementError("Qoder CN CLI is unavailable in this release")
    return qoder_status()


def _extract_login_url(line: str) -> str | None:
    for candidate in re.findall(r"https://\S+", line):
        value = candidate.rstrip(".,;:)]}'\"")
        parsed = urlsplit(value)
        if (
            parsed.scheme == "https"
            and parsed.hostname in QODERCN_LOGIN_HOSTS
            and parsed.path == "/device/selectAccounts"
            and any(parse_qs(parsed.query).get("challenge", []))
        ):
            return value
    return None


def _read_login_output(process: subprocess.Popen[str]) -> None:
    global _LOGIN_ERROR, _LOGIN_PROCESS, _LOGIN_URL
    try:
        assert process.stdout is not None
        for line in process.stdout:
            login_url = _extract_login_url(line)
            if login_url:
                with _LOGIN_LOCK:
                    _LOGIN_URL = login_url
        return_code = process.wait()
        with _LOGIN_LOCK:
            if return_code != 0:
                _LOGIN_ERROR = "Qoder login did not complete"
    finally:
        with _LOGIN_LOCK:
            _LOGIN_PROCESS = None
            _LOGIN_URL = None


def start_login() -> dict[str, object]:
    global _LOGIN_ERROR, _LOGIN_PROCESS, _LOGIN_URL
    _require_enabled()
    cli = _cli_path()
    if cli is None:
        raise QoderManagementError("Install Qoder before login")
    current = qoder_status()
    if current["authenticated"]:
        return current
    with _LOGIN_LOCK:
        if _LOGIN_PROCESS is None or _LOGIN_PROCESS.poll() is not None:
            _LOGIN_ERROR = None
            _LOGIN_URL = None
            try:
                _LOGIN_PROCESS = subprocess.Popen(
                    [str(cli), "login"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                    env=_qodercn_env(),
                )
            except OSError as exc:
                raise QoderManagementError("Qoder login could not start") from exc
            threading.Thread(target=_read_login_output, args=(_LOGIN_PROCESS,), daemon=True).start()
    for _ in range(50):
        with _LOGIN_LOCK:
            if _LOGIN_URL or _LOGIN_ERROR:
                break
        time.sleep(0.1)
    return qoder_status()


def start_service() -> dict[str, object]:
    _require_enabled()
    cli = _cli_path()
    if cli is None:
        raise QoderManagementError("Install Qoder before starting the service")
    status = qoder_status()
    if not status["authenticated"]:
        raise QoderManagementError("Login to Qoder before starting the service")
    if status["service_running"]:
        return status
    runtime = _runtime_dir()
    log_path = runtime / "remote-control.log"
    with log_path.open("a", encoding="utf-8") as log:
        try:
            process = subprocess.Popen(
                [
                    str(cli), "remote-control", "--name", "LMateLab-107Cup",
                    "--spawn", "same-dir", "--capacity", "1",
                    "--directory", str(_workspace_dir()),
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=_qodercn_env(),
            )
        except OSError as exc:
            raise QoderManagementError("Qoder service could not start") from exc
    (runtime / "remote-control.pid").write_text(f"{process.pid}\n", encoding="ascii")
    time.sleep(0.5)
    if process.poll() is not None:
        (runtime / "remote-control.pid").unlink(missing_ok=True)
        raise QoderManagementError("Qoder service exited during startup")
    return qoder_status()


def stop_service() -> dict[str, object]:
    _require_enabled()
    pid = _service_pid()
    if pid is None:
        return qoder_status()
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
    except OSError as exc:
        raise QoderManagementError("Qoder service identity cannot be verified") from exc
    if "qoderclicn" not in command or "remote-control" not in command:
        raise QoderManagementError("Qoder service identity does not match")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        raise QoderManagementError("Qoder service could not be stopped") from exc
    (_runtime_dir() / "remote-control.pid").unlink(missing_ok=True)
    return qoder_status()
