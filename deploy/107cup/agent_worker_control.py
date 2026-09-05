#!/usr/bin/env python3
"""Owned, duplicate-safe control for the 107 Cup Agent worker Slurm job."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows contract tests
    fcntl = None


ROOT = Path("/home/scc/pb23030683/lmatelab-107cup")
PROJECT = Path("/home/scc/pb23030683/projects/LMateLab-107Cup")
WORKER_SCRIPT = PROJECT / "deploy" / "107cup" / "agent-worker.slurm"
SCONTROL = Path("/usr/bin/scontrol")
SQUEUE = Path("/usr/bin/squeue")
SBATCH = Path("/usr/bin/sbatch")
ACTIVE_STATES = (
    "CONFIGURING,COMPLETING,PENDING,REQUEUED,RUNNING,RESIZING,SUSPENDED"
)
JOB_ID = re.compile(r"^[1-9][0-9]*$")
NODE = re.compile(r"^anode(?:0[1-9]|1[0-9]|2[0-6])$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
STATE_SCHEMA = "lmatelab-107cup-agent-worker-state-v1"
RECOVERY_SCHEMA = "lmatelab-107cup-agent-worker-recovery-v1"


class AgentWorkerControlError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate(pattern: re.Pattern[str], value: str, name: str) -> str:
    if not pattern.fullmatch(value):
        raise AgentWorkerControlError(f"invalid_{name}")
    return value


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent), text=True
    )
    temporary = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def _lock():
    runtime = ROOT / "runtime"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = runtime / "agent-worker-recovery.lock"
    with path.open("a+", encoding="utf-8") as handle:
        path.chmod(0o600)
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _parse_job(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in shlex.split(output.strip()):
        if "=" in token:
            key, value = token.split("=", 1)
            fields[key] = value
    required = (
        "JobId", "JobState", "JobName", "UserId", "Command",
        "WorkDir", "Account", "Partition", "QOS",
    )
    if any(not fields.get(name) for name in required):
        raise AgentWorkerControlError("invalid_scontrol_record")
    fields["UserName"] = fields["UserId"].split("(", 1)[0]
    return fields


def _owned(fields: dict[str, str]) -> bool:
    return (
        fields["JobName"] == "lmatelab-agent-worker"
        and fields["UserName"] == "pb23030683"
        and fields["Command"] == str(WORKER_SCRIPT)
        and fields["WorkDir"] in {str(PROJECT), "/home/scc/pb23030683"}
        and fields["Account"] == "competition"
        and fields["Partition"] == "P107-A100"
        and fields["QOS"] == "qos_p107-a100"
    )


def _lookup(job_id: str) -> dict[str, str] | None:
    _validate(JOB_ID, job_id, "job_id")
    result = subprocess.run(
        [str(SCONTROL), "show", "job", "-o", job_id],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode == 0 and result.stdout.strip():
        return _parse_job(result.stdout)
    if "invalid job id" in f"{result.stdout}\n{result.stderr}".lower():
        return None
    raise AgentWorkerControlError("scheduler_lookup_unavailable")


def _active_workers() -> list[dict[str, str]]:
    result = subprocess.run(
        [
            str(SQUEUE), "--noheader", "--user", "pb23030683",
            "--name", "lmatelab-agent-worker", "--states", ACTIVE_STATES,
            "--format", "%A",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise AgentWorkerControlError("scheduler_queue_unavailable")
    jobs = []
    for job_id in sorted(set(result.stdout.split())):
        fields = _lookup(job_id)
        if fields is None:
            continue
        if not _owned(fields):
            raise AgentWorkerControlError("candidate_ownership_mismatch")
        jobs.append(fields)
    return jobs


def recover() -> str:
    with _lock():
        jobs = _active_workers()
        if len(jobs) > 1:
            raise AgentWorkerControlError("multiple_owned_workers")
        if jobs:
            job_id = jobs[0]["JobId"]
            action = "reused"
        else:
            result = subprocess.run(
                [str(SBATCH), "--parsable", str(WORKER_SCRIPT)],
                cwd=str(PROJECT),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise AgentWorkerControlError("worker_submission_failed")
            job_id = result.stdout.strip().split(";", 1)[0]
            _validate(JOB_ID, job_id, "job_id")
            action = "submitted"
        _atomic_json(
            ROOT / "runtime" / "agent-worker-recovery-state.json",
            {
                "schema": RECOVERY_SCHEMA,
                "candidate_job_id": job_id,
                "action": action,
                "updated_at": _now(),
            },
        )
        print(job_id)
        return job_id


def publish(args: argparse.Namespace) -> None:
    job_id = _validate(JOB_ID, args.job_id, "job_id")
    node = _validate(NODE, args.node, "node")
    commit = _validate(SHA40, args.commit, "commit")
    manifest = _validate(SHA256, args.manifest_sha256, "manifest")
    fields = _lookup(job_id)
    if fields is None or not _owned(fields):
        raise AgentWorkerControlError("candidate_ownership_mismatch")
    payload: dict[str, object] = {
        "schema": STATE_SCHEMA,
        "job_id": job_id,
        "node": node,
        "commit": commit,
        "manifest_sha256": manifest,
        "started_at": args.started_at,
        "status": args.status,
        "updated_at": _now(),
    }
    if args.exit_code is not None:
        payload["exit_code"] = args.exit_code
    _atomic_json(ROOT / "runtime" / "agent-worker-state.json", payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("recover")
    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--job-id", required=True)
    publish_parser.add_argument("--node", required=True)
    publish_parser.add_argument("--commit", required=True)
    publish_parser.add_argument("--manifest-sha256", required=True)
    publish_parser.add_argument("--started-at", required=True)
    publish_parser.add_argument("--status", choices=("running", "stopped"), required=True)
    publish_parser.add_argument("--exit-code", type=int)
    args = parser.parse_args()
    if args.command == "recover":
        recover()
    else:
        publish(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
