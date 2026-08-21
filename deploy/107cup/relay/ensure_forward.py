#!/usr/bin/env python3
"""Keep the 4090 user relay bound to the verified 107 service runtime."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, NamedTuple, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows contract tests
    fcntl = None


CONFIG_ROOT = Path("/home/Pwjb/.config/lmatelab-107cup-proxy")
CONTROL_SOCKET = Path("/home/Pwjb/.ssh/cm-107cup")
REMOTE = "pb23030683@107.ustc.edu.cn"
REMOTE_RECOVERY = "/home/scc/pb23030683/projects/LMateLab-107Cup/deploy/107cup/recover-service.sh"
MAIN_PORT = 18740
PROBE_PORT = 18742
PUBLIC_PORT = 18733
SSH = "/usr/bin/ssh"
TIMEOUT = "/usr/bin/timeout"
NGINX = "/usr/sbin/nginx"
JOB_ID = re.compile(r"^[1-9][0-9]*$")
NODE = re.compile(r"^anode(0[1-9]|1[0-9]|2[0-6])$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RelayRecoveryError(RuntimeError):
    pass


class DesiredRuntime(NamedTuple):
    job_id: str
    node: str
    port: int
    commit: str
    manifest_sha256: str

    def as_state(self) -> dict:
        return {
            "schema": "lmatelab-107cup-forward-state-v1",
            "job_id": self.job_id,
            "node": self.node,
            "target_host": node_to_target(self.node),
            "port": self.port,
            "commit": self.commit,
            "manifest_sha256": self.manifest_sha256,
        }


def node_to_target(node: str) -> str:
    match = NODE.fullmatch(node)
    if match is None:
        raise ValueError("invalid 107 compute node")
    number = int(match.group(1))
    return f"11.11.10.{number}"


def _validate_desired(payload: dict) -> DesiredRuntime:
    job_id = str(payload.get("job_id", ""))
    node = str(payload.get("node", ""))
    port = payload.get("port")
    commit = str(payload.get("commit", ""))
    manifest = str(payload.get("manifest_sha256", ""))
    if not JOB_ID.fullmatch(job_id):
        raise RelayRecoveryError("invalid_job_id")
    node_to_target(node)
    if isinstance(port, bool) or not isinstance(port, int) or port != 18731:
        raise RelayRecoveryError("invalid_service_port")
    if not SHA40.fullmatch(commit):
        raise RelayRecoveryError("invalid_commit")
    if not SHA256.fullmatch(manifest):
        raise RelayRecoveryError("invalid_manifest")
    return DesiredRuntime(job_id, node, port, commit, manifest)


def parse_remote_result(text: str) -> tuple[str, Optional[DesiredRuntime], dict]:
    if len(text.encode("utf-8")) > 4096:
        raise RelayRecoveryError("remote_result_oversized")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RelayRecoveryError("remote_result_not_single_json")
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise RelayRecoveryError("remote_result_invalid") from exc
    if not isinstance(payload, dict):
        raise RelayRecoveryError("remote_result_invalid")
    status = payload.get("status")
    if status not in {"ready", "waiting", "submitted", "blocked"}:
        raise RelayRecoveryError("remote_status_invalid")
    desired = _validate_desired(payload) if status == "ready" else None
    reason = payload.get("reason")
    if reason is not None and (not isinstance(reason, str) or not re.fullmatch(r"[a-z0-9_]+", reason)):
        raise RelayRecoveryError("remote_reason_invalid")
    return status, desired, payload


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        else:  # pragma: no cover - Windows contract tests
            os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _read_state(path: Path) -> Optional[DesiredRuntime]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
        raise RelayRecoveryError("forward_state_unsafe")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise RelayRecoveryError("forward_state_changed")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            payload = json.load(handle)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if payload.get("schema") != "lmatelab-107cup-forward-state-v1":
        raise RelayRecoveryError("forward_state_schema_mismatch")
    desired = _validate_desired(payload)
    if payload.get("target_host") != node_to_target(desired.node):
        raise RelayRecoveryError("forward_target_mismatch")
    return desired


def _expected_live(desired: DesiredRuntime) -> dict:
    return {
        "status": "ok",
        "job_id": desired.job_id,
        "node": desired.node,
        "commit": desired.commit,
        "manifest_sha256": desired.manifest_sha256,
        "release_kind": "stable",
        "data_mode": "live",
    }


def _matches(desired: DesiredRuntime, live: dict, ready: dict) -> bool:
    expected = _expected_live(desired)
    return all(live.get(key) == value for key, value in expected.items()) and ready == {
        "status": "ready"
    }


class ForwardReconciler:
    def __init__(self, *, state_path: Path, control, probe: Callable, gateway):
        self.state_path = state_path
        self.control = control
        self.probe = probe
        self.gateway = gateway

    def reconcile(self, desired: DesiredRuntime) -> dict:
        current = _read_state(self.state_path)
        try:
            live, ready = self.probe(MAIN_PORT)
            main_matches = _matches(desired, live, ready)
        except Exception:
            main_matches = False
        if main_matches:
            self.gateway.ensure_running()
            public_live, public_ready = self.gateway.probe_public()
            if not _matches(desired, public_live, public_ready):
                raise RelayRecoveryError("public_identity_mismatch")
            _atomic_write_json(self.state_path, desired.as_state())
            return {"status": "ready", **desired.as_state()}
        if current is None:
            raise RelayRecoveryError("unknown_existing_forward")

        new_target = node_to_target(desired.node)
        old_target = node_to_target(current.node)
        self.control.forward(PROBE_PORT, new_target, desired.port)
        probe_active = True
        switched = False
        try:
            try:
                candidate_live, candidate_ready = self.probe(PROBE_PORT)
            except Exception as exc:
                raise RelayRecoveryError("candidate_unavailable") from exc
            if not _matches(desired, candidate_live, candidate_ready):
                raise RelayRecoveryError("candidate_identity_mismatch")

            self.control.cancel(MAIN_PORT, old_target, current.port)
            try:
                self.control.forward(MAIN_PORT, new_target, desired.port)
                switched = True
            except Exception:
                self.control.forward(MAIN_PORT, old_target, current.port)
                raise

            live, ready = self.probe(MAIN_PORT)
            if not _matches(desired, live, ready):
                raise RelayRecoveryError("switched_forward_identity_mismatch")
            self.control.cancel(PROBE_PORT, new_target, desired.port)
            probe_active = False
            self.gateway.ensure_running()
            public_live, public_ready = self.gateway.probe_public()
            if not _matches(desired, public_live, public_ready):
                raise RelayRecoveryError("public_identity_mismatch")
            _atomic_write_json(self.state_path, desired.as_state())
            return {"status": "switched", **desired.as_state()}
        except Exception:
            if switched:
                try:
                    self.control.cancel(MAIN_PORT, new_target, desired.port)
                    self.control.forward(MAIN_PORT, old_target, current.port)
                except Exception as rollback_error:
                    raise RelayRecoveryError("forward_rollback_failed") from rollback_error
            raise
        finally:
            if probe_active:
                try:
                    self.control.cancel(PROBE_PORT, new_target, desired.port)
                except Exception:
                    pass


class SubprocessControl:
    def check(self) -> None:
        completed = subprocess.run(
            [SSH, "-S", str(CONTROL_SOCKET), "-O", "check", REMOTE],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            raise RelayRecoveryError("ssh_authentication_required")

    def remote_recovery(self) -> str:
        completed = subprocess.run(
            [
                TIMEOUT,
                "45",
                SSH,
                "-S",
                str(CONTROL_SOCKET),
                "-o",
                "BatchMode=yes",
                REMOTE,
                "/bin/bash",
                REMOTE_RECOVERY,
            ],
            capture_output=True,
            text=True,
            timeout=50,
            check=False,
        )
        if completed.returncode != 0:
            raise RelayRecoveryError("remote_recovery_failed")
        return completed.stdout

    def forward(self, bind_port: int, target_host: str, target_port: int) -> None:
        specification = f"127.0.0.1:{bind_port}:{target_host}:{target_port}"
        self._control("forward", specification)

    def cancel(self, bind_port: int, target_host: str, target_port: int) -> None:
        specification = f"127.0.0.1:{bind_port}:{target_host}:{target_port}"
        self._control("cancel", specification)

    @staticmethod
    def _control(operation: str, specification: str) -> None:
        completed = subprocess.run(
            [SSH, "-S", str(CONTROL_SOCKET), "-O", operation, "-L", specification, REMOTE],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if completed.returncode != 0:
            raise RelayRecoveryError(f"ssh_{operation}_failed")


def probe_local(port: int) -> tuple[dict, dict]:
    def fetch(path: str) -> dict:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=8) as response:
                body = response.read(4097)
        except (OSError, urllib.error.URLError) as exc:
            raise RelayRecoveryError("relay_health_unavailable") from exc
        if len(body) > 4096:
            raise RelayRecoveryError("relay_health_oversized")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RelayRecoveryError("relay_health_invalid") from exc
        if not isinstance(payload, dict):
            raise RelayRecoveryError("relay_health_invalid")
        return payload

    return fetch("/api/health/live"), fetch("/api/health/ready")


class NginxGateway:
    config = CONFIG_ROOT / "conf" / "nginx.conf"
    pid_file = CONFIG_ROOT / "run" / "nginx.pid"

    def ensure_running(self) -> None:
        if self._running():
            return
        check = subprocess.run(
            [NGINX, "-t", "-c", str(self.config)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if check.returncode != 0:
            raise RelayRecoveryError("nginx_config_invalid")
        started = subprocess.run(
            [NGINX, "-c", str(self.config)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if started.returncode != 0 or not self._running():
            raise RelayRecoveryError("nginx_start_failed")

    def _running(self) -> bool:
        try:
            value = self.pid_file.read_text(encoding="utf-8").strip()
            pid = int(value)
            os.kill(pid, 0)
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            return False
        return pid > 1

    def probe_public(self) -> tuple[dict, dict]:
        return probe_local(PUBLIC_PORT)


def _write_status(payload: dict) -> None:
    payload = {"schema": "lmatelab-107cup-relay-recovery-v1", **payload}
    _atomic_write_json(CONFIG_ROOT / "state" / "recovery-status.json", payload)


def maintenance_enabled(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size > 256:
        raise RelayRecoveryError("maintenance_marker_unsafe")
    return True


def adopt_current_forward(
    state_path: Path, probe: Callable[[int], tuple[dict, dict]] = probe_local
) -> DesiredRuntime:
    live, ready = probe(MAIN_PORT)
    desired = _validate_desired(
        {
            "job_id": live.get("job_id"),
            "node": live.get("node"),
            "port": 18731,
            "commit": live.get("commit"),
            "manifest_sha256": live.get("manifest_sha256"),
        }
    )
    if not _matches(desired, live, ready):
        raise RelayRecoveryError("existing_forward_identity_invalid")
    _atomic_write_json(state_path, desired.as_state())
    return desired


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    state_dir = CONFIG_ROOT / "state"
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if arguments:
        if arguments != ["--adopt-current"]:
            raise SystemExit("only --adopt-current is supported")
        try:
            desired = adopt_current_forward(state_dir / "forward-state.json")
            result = {"status": "adopted", **desired.as_state()}
            _write_status(result)
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0
        except RelayRecoveryError as exc:
            result = {"status": "blocked", "reason": str(exc)}
            _write_status(result)
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 2
    try:
        if maintenance_enabled(state_dir / "maintenance"):
            result = {"status": "maintenance", "reason": "operator_requested"}
            _write_status(result)
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0
    except RelayRecoveryError as exc:
        result = {"status": "blocked", "reason": str(exc)}
        _write_status(result)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 2
    lock_path = state_dir / "recovery.lock"
    try:
        with lock_path.open("a+", encoding="utf-8") as lock:
            lock_path.chmod(0o600)
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            control = SubprocessControl()
            control.check()
            status, desired, remote_payload = parse_remote_result(control.remote_recovery())
            if status != "ready":
                result = {"status": status, "reason": remote_payload.get("reason", status)}
                if "job_id" in remote_payload:
                    result["job_id"] = remote_payload["job_id"]
                _write_status(result)
                print(json.dumps(result, sort_keys=True, separators=(",", ":")))
                return 2 if status == "blocked" else 0
            assert desired is not None
            result = ForwardReconciler(
                state_path=state_dir / "forward-state.json",
                control=control,
                probe=probe_local,
                gateway=NginxGateway(),
            ).reconcile(desired)
            _write_status(result)
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0
    except BlockingIOError:
        return 0
    except RelayRecoveryError as exc:
        result = {"status": "blocked", "reason": str(exc)}
        _write_status(result)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    sys.exit(main())
