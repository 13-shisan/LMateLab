#!/usr/bin/env python3
"""Bounded service recovery for the 107 Cup Slurm deployment."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, NamedTuple, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows contract tests
    fcntl = None


ROOT = Path("/home/scc/pb23030683/lmatelab-107cup")
PROJECT = Path("/home/scc/pb23030683/projects/LMateLab-107Cup")
SERVICE_SCRIPT = PROJECT / "deploy" / "107cup" / "service.slurm"
SCONTROL = Path("/usr/bin/scontrol")
SBATCH = Path("/usr/bin/sbatch")
SERVICE_STATE_SCHEMA = "lmatelab-107cup-service-state-v1"
RECOVERY_STATE_SCHEMA = "lmatelab-107cup-service-recovery-v1"
ACTIVE_STATES = {
    "CONFIGURING",
    "COMPLETING",
    "PENDING",
    "REQUEUED",
    "RUNNING",
    "RESIZING",
    "SUSPENDED",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
JOB_ID = re.compile(r"^[1-9][0-9]*$")
NODE = re.compile(r"^anode(?:0[1-9]|1[0-9]|2[0-6])$")


class RecoveryError(RuntimeError):
    pass


class SchedulerUnavailable(RecoveryError):
    pass


class HealthProbeError(RecoveryError):
    pass


class JobRecord(NamedTuple):
    job_id: str
    state: str
    job_name: str
    user_name: str
    command: str
    work_dir: str
    account: str
    partition: str
    qos: str
    node: str


def _validate_job_id(value: str) -> str:
    if not JOB_ID.fullmatch(value):
        raise RecoveryError("invalid_job_id")
    return value


def _validate_node(value: str) -> str:
    if not NODE.fullmatch(value):
        raise RecoveryError("invalid_node")
    return value


def node_to_address(node: str) -> str:
    node = _validate_node(node)
    return f"11.11.10.{int(node[5:])}"


def _validate_port(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1024 <= value <= 65535:
        raise RecoveryError("invalid_port")
    return value


def _validate_commit(value: str) -> str:
    if not SHA40.fullmatch(value):
        raise RecoveryError("invalid_commit")
    return value


def _validate_manifest(value: str) -> str:
    if not SHA256.fullmatch(value):
        raise RecoveryError("invalid_manifest")
    return value


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent), text=True
    )
    temporary = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        else:  # pragma: no cover - Windows contract tests
            os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            handle.write(text)
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


def _atomic_write_json(path: Path, payload: dict) -> None:
    _atomic_write_text(
        path,
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    )


def _secure_read_json(path: Path, *, required: bool = False) -> Optional[dict]:
    try:
        before = path.lstat()
    except FileNotFoundError:
        if required:
            raise RecoveryError(f"missing_{path.name}")
        return None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise RecoveryError(f"unsafe_{path.name}")
    if before.st_size > 4096:
        raise RecoveryError(f"oversized_{path.name}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise RecoveryError(f"changed_{path.name}")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            payload = json.load(handle)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise RecoveryError(f"invalid_{path.name}")
    return payload


@contextmanager
def recovery_lock(runtime_dir: Path):
    runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = runtime_dir / "service-recovery.lock"
    with path.open("a+", encoding="utf-8") as handle:
        path.chmod(0o600)
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def parse_scontrol_job(output: str) -> JobRecord:
    fields = {}
    for token in shlex.split(output.strip()):
        if "=" in token:
            key, value = token.split("=", 1)
            fields[key] = value
    required = (
        "JobId",
        "JobState",
        "JobName",
        "UserId",
        "Command",
        "WorkDir",
        "Account",
        "Partition",
        "QOS",
    )
    if any(not fields.get(name) for name in required):
        raise RecoveryError("invalid_scontrol_record")
    user_name = fields["UserId"].split("(", 1)[0]
    node = fields.get("NodeList", "")
    if node == "(null)":
        node = ""
    return JobRecord(
        job_id=_validate_job_id(fields["JobId"]),
        state=fields["JobState"].upper(),
        job_name=fields["JobName"],
        user_name=user_name,
        command=fields["Command"],
        work_dir=fields["WorkDir"],
        account=fields["Account"],
        partition=fields["Partition"],
        qos=fields["QOS"],
        node=node,
    )


def is_owned_service_job(record: JobRecord, project_dir: Path) -> bool:
    service_script = project_dir / "deploy" / "107cup" / "service.slurm"
    allowed_work_dirs = {str(project_dir), "/home/scc/pb23030683"}
    return (
        record.job_name == "lmatelab-web"
        and record.user_name == "pb23030683"
        and record.command == str(service_script)
        and record.work_dir in allowed_work_dirs
        and record.account == "competition"
        and record.partition == "P107-A100"
        and record.qos == "qos_p107-a100"
    )


class SubprocessScheduler:
    def lookup(self, job_id: str) -> Optional[JobRecord]:
        job_id = _validate_job_id(job_id)
        completed = subprocess.run(
            [str(SCONTROL), "show", "job", "-o", job_id],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return parse_scontrol_job(completed.stdout)
        combined = f"{completed.stdout}\n{completed.stderr}".lower()
        if "invalid job id" in combined:
            return None
        raise SchedulerUnavailable("scheduler_lookup_unavailable")

    def submit(self, script: Path, work_dir: Path) -> str:
        if script != SERVICE_SCRIPT or work_dir != PROJECT:
            raise RecoveryError("submission_scope_mismatch")
        completed = subprocess.run(
            [str(SBATCH), "--parsable", str(script)],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            raise SchedulerUnavailable("service_submission_failed")
        return _validate_job_id(completed.stdout.strip().split(";", 1)[0])


def load_release_identity(root: Path = ROOT) -> tuple[str, str]:
    current = root / "current"
    if not current.is_symlink():
        raise RecoveryError("current_is_not_symlink")
    release = current.resolve(strict=True)
    expected_parent = (root / "releases").resolve(strict=True)
    if release.parent != expected_parent:
        raise RecoveryError("current_release_escape")
    commit = _validate_commit(release.name)
    if (release / "commit.txt").read_text(encoding="utf-8").strip() != commit:
        raise RecoveryError("release_commit_mismatch")
    manifest_line = (release / "manifest.sha256").read_text(encoding="utf-8").splitlines()[0]
    manifest = _validate_manifest(manifest_line.split()[0])
    return commit, manifest


def probe_health(node: str, port: int) -> tuple[dict, dict]:
    address = node_to_address(node)
    _validate_port(port)

    def fetch(path: str) -> dict:
        url = f"http://{address}:{port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read(4097)
        except (OSError, urllib.error.URLError) as exc:
            raise HealthProbeError("health_unavailable") from exc
        if len(body) > 4096:
            raise HealthProbeError("health_oversized")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HealthProbeError("health_invalid") from exc
        if not isinstance(payload, dict):
            raise HealthProbeError("health_invalid")
        return payload

    return fetch("/api/health/live"), fetch("/api/health/ready")


def _validate_service_state(payload: dict) -> dict:
    if payload.get("schema") != SERVICE_STATE_SCHEMA:
        raise RecoveryError("service_state_schema_mismatch")
    result = {
        "schema": SERVICE_STATE_SCHEMA,
        "job_id": _validate_job_id(str(payload.get("job_id", ""))),
        "node": _validate_node(str(payload.get("node", ""))),
        "port": _validate_port(payload.get("port")),
        "commit": _validate_commit(str(payload.get("commit", ""))),
        "manifest_sha256": _validate_manifest(str(payload.get("manifest_sha256", ""))),
        "started_at": str(payload.get("started_at", "")),
    }
    if not result["started_at"] or len(result["started_at"]) > 64:
        raise RecoveryError("invalid_started_at")
    return result


def _default_recovery_state() -> dict:
    return {
        "schema": RECOVERY_STATE_SCHEMA,
        "candidate_job_id": None,
        "attempt_count": 0,
        "submitted_at": None,
    }


def _validate_recovery_state(payload: Optional[dict]) -> dict:
    if payload is None:
        return _default_recovery_state()
    if payload.get("schema") != RECOVERY_STATE_SCHEMA:
        raise RecoveryError("recovery_state_schema_mismatch")
    candidate = payload.get("candidate_job_id")
    if candidate is not None:
        candidate = _validate_job_id(str(candidate))
    attempts = payload.get("attempt_count")
    submitted_at = payload.get("submitted_at")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 0 <= attempts <= 100:
        raise RecoveryError("invalid_attempt_count")
    if submitted_at is not None and not isinstance(submitted_at, (int, float)):
        raise RecoveryError("invalid_submitted_at")
    return {
        "schema": RECOVERY_STATE_SCHEMA,
        "candidate_job_id": candidate,
        "attempt_count": attempts,
        "submitted_at": submitted_at,
    }


def _health_matches(state: dict, live: dict, ready: dict) -> bool:
    expected = {
        "status": "ok",
        "job_id": state["job_id"],
        "node": state["node"],
        "commit": state["commit"],
        "manifest_sha256": state["manifest_sha256"],
        "release_kind": "stable",
        "data_mode": "live",
    }
    return all(live.get(key) == value for key, value in expected.items()) and ready == {
        "status": "ready"
    }


class ServiceRecovery:
    def __init__(
        self,
        *,
        runtime_dir: Path,
        project_dir: Path,
        scheduler,
        health_probe: Callable[[str, int], tuple[dict, dict]],
        release_identity: Callable[[], tuple[str, str]],
        clock: Callable[[], float] = time.time,
        retry_delay_seconds: int = 300,
        max_attempts: int = 3,
    ):
        self.runtime_dir = runtime_dir
        self.project_dir = project_dir
        self.scheduler = scheduler
        self.health_probe = health_probe
        self.release_identity = release_identity
        self.clock = clock
        self.retry_delay_seconds = retry_delay_seconds
        self.max_attempts = max_attempts

    @property
    def service_script(self) -> Path:
        return self.project_dir / "deploy" / "107cup" / "service.slurm"

    def run(self) -> dict:
        commit, manifest = self.release_identity()
        _validate_commit(commit)
        _validate_manifest(manifest)
        state_payload = _secure_read_json(self.runtime_dir / "service-state.json")
        if state_payload is not None:
            state = _validate_service_state(state_payload)
            if state["commit"] != commit or state["manifest_sha256"] != manifest:
                return {"status": "blocked", "reason": "release_identity_mismatch"}
            result = self._inspect_published(state)
            if result is not None:
                return result
        else:
            legacy = self._inspect_legacy_job()
            if legacy is not None:
                return legacy
        return self._recover_candidate(commit, manifest)

    def _lookup(self, job_id: str) -> Optional[JobRecord]:
        try:
            return self.scheduler.lookup(job_id)
        except SchedulerUnavailable:
            raise
        except Exception as exc:
            raise SchedulerUnavailable("scheduler_lookup_unavailable") from exc

    def _inspect_published(self, state: dict) -> Optional[dict]:
        try:
            record = self._lookup(state["job_id"])
        except SchedulerUnavailable:
            return {"status": "blocked", "reason": "scheduler_unavailable"}
        if record is None:
            return None
        if not is_owned_service_job(record, self.project_dir):
            return {"status": "blocked", "reason": "service_ownership_mismatch"}
        if record.state not in ACTIVE_STATES:
            return None
        if record.state != "RUNNING":
            return {
                "status": "waiting",
                "reason": "service_active_not_running",
                "job_id": state["job_id"],
            }
        if record.node and record.node != state["node"]:
            return {"status": "blocked", "reason": "service_node_mismatch"}
        try:
            live, ready = self.health_probe(state["node"], state["port"])
        except HealthProbeError:
            return {
                "status": "waiting",
                "reason": "service_not_ready",
                "job_id": state["job_id"],
            }
        if not _health_matches(state, live, ready):
            return {"status": "blocked", "reason": "service_identity_mismatch"}
        return {"status": "ready", **{key: state[key] for key in state if key != "schema"}}

    def _inspect_legacy_job(self) -> Optional[dict]:
        path = self.runtime_dir / "service-job-id"
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        try:
            job_id = _validate_job_id(value)
            record = self._lookup(job_id)
        except (RecoveryError, SchedulerUnavailable):
            return {"status": "blocked", "reason": "legacy_state_unverifiable"}
        if record is None:
            return None
        if not is_owned_service_job(record, self.project_dir):
            return {"status": "blocked", "reason": "legacy_ownership_mismatch"}
        if record.state in ACTIVE_STATES:
            return {"status": "waiting", "reason": "legacy_state_active", "job_id": job_id}
        return None

    def _recover_candidate(self, commit: str, manifest: str) -> dict:
        path = self.runtime_dir / "service-recovery-state.json"
        try:
            recovery = _validate_recovery_state(_secure_read_json(path))
        except RecoveryError:
            return {"status": "blocked", "reason": "recovery_state_invalid"}
        candidate = recovery["candidate_job_id"]
        if candidate is not None:
            try:
                record = self._lookup(candidate)
            except SchedulerUnavailable:
                return {"status": "blocked", "reason": "scheduler_unavailable"}
            if record is not None:
                if not is_owned_service_job(record, self.project_dir):
                    return {"status": "blocked", "reason": "candidate_ownership_mismatch"}
                if record.state in ACTIVE_STATES:
                    return {
                        "status": "waiting",
                        "reason": "candidate_active",
                        "job_id": candidate,
                    }
            submitted_at = recovery["submitted_at"]
            if submitted_at is not None and self.clock() - submitted_at < self.retry_delay_seconds:
                return {
                    "status": "waiting",
                    "reason": "retry_cooldown",
                    "job_id": candidate,
                }
        if recovery["attempt_count"] >= self.max_attempts:
            return {"status": "blocked", "reason": "retry_budget_exhausted"}
        if not self.service_script.is_file():
            return {"status": "blocked", "reason": "service_script_missing"}
        try:
            job_id = self.scheduler.submit(self.service_script, self.project_dir)
            _validate_job_id(job_id)
        except (RecoveryError, SchedulerUnavailable):
            return {"status": "blocked", "reason": "service_submission_failed"}
        recovery = {
            "schema": RECOVERY_STATE_SCHEMA,
            "candidate_job_id": job_id,
            "attempt_count": recovery["attempt_count"] + 1,
            "submitted_at": self.clock(),
            "release_commit": commit,
            "manifest_sha256": manifest,
        }
        _atomic_write_json(path, recovery)
        return {"status": "submitted", "reason": "service_missing", "job_id": job_id}


def publish_service_state(
    *,
    runtime_dir: Path,
    job_id: str,
    node: str,
    port: int,
    commit: str,
    manifest_sha256: str,
    started_at: str,
) -> dict:
    payload = _validate_service_state(
        {
            "schema": SERVICE_STATE_SCHEMA,
            "job_id": job_id,
            "node": node,
            "port": port,
            "commit": commit,
            "manifest_sha256": manifest_sha256,
            "started_at": started_at,
        }
    )
    recovery_path = runtime_dir / "service-recovery-state.json"
    recovery = _validate_recovery_state(_secure_read_json(recovery_path))
    candidate = recovery["candidate_job_id"]
    if candidate is not None and candidate != payload["job_id"]:
        raise RecoveryError("candidate_publish_mismatch")
    for name, value in (
        ("service-job-id", payload["job_id"]),
        ("service-node", payload["node"]),
        ("service-port", str(payload["port"])),
        ("service-commit", payload["commit"]),
        ("service-manifest-sha256", payload["manifest_sha256"]),
        ("service-started-at", payload["started_at"]),
    ):
        _atomic_write_text(runtime_dir / name, f"{value}\n")
    _atomic_write_json(runtime_dir / "service-state.json", payload)
    _atomic_write_json(recovery_path, _default_recovery_state())
    return payload


def _recover_cli() -> int:
    with recovery_lock(ROOT / "runtime"):
        result = ServiceRecovery(
            runtime_dir=ROOT / "runtime",
            project_dir=PROJECT,
            scheduler=SubprocessScheduler(),
            health_probe=probe_health,
            release_identity=lambda: load_release_identity(ROOT),
        ).run()
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def _publish_cli(arguments) -> int:
    with recovery_lock(ROOT / "runtime"):
        payload = publish_service_state(
            runtime_dir=ROOT / "runtime",
            job_id=arguments.job_id,
            node=arguments.node,
            port=arguments.port,
            commit=arguments.commit,
            manifest_sha256=arguments.manifest_sha256,
            started_at=arguments.started_at,
        )
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("recover")
    publish = subparsers.add_parser("publish")
    publish.add_argument("--job-id", required=True)
    publish.add_argument("--node", required=True)
    publish.add_argument("--port", required=True, type=int)
    publish.add_argument("--commit", required=True)
    publish.add_argument("--manifest-sha256", required=True)
    publish.add_argument("--started-at", required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "recover":
            return _recover_cli()
        return _publish_cli(arguments)
    except RecoveryError as exc:
        print(
            json.dumps(
                {"status": "blocked", "reason": str(exc)},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
