#!/home/scc/pb23030683/lmatelab-107cup/envs/python/bin/python
#SBATCH --job-name=lmatelab-stage6-smoke
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=512M
#SBATCH --time=00:10:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/stage6-smoke-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/stage6-smoke-%j.err

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path


MAX_OUTPUT_BYTES = 1024 * 1024
POLL_SECONDS = 1.0
PROBE_TIMEOUT_SECONDS = 120.0
EVIDENCE_PARENT = Path("/home/scc/pb23030683/lmatelab-107cup/evidence/stage6")
SLURM_JOB_ID = os.environ.get("SLURM_JOB_ID", "")
if re.fullmatch(r"[1-9][0-9]*", SLURM_JOB_ID) is None:
    raise SystemExit("SLURM_JOB_ID is required; submit stage6-smoke.py through Slurm")

EVIDENCE_ROOT = EVIDENCE_PARENT / f"job-{SLURM_JOB_ID}"
DATABASE_PATH = EVIDENCE_ROOT / "stage6-smoke.sqlite"
WORKFLOW_ROOT = EVIDENCE_ROOT / "workflows"
os.environ["DATABASE_URL"] = f"sqlite:///{DATABASE_PATH}"

SCRIPT_PATH = Path(__file__).resolve()
SOURCE_ROOT = SCRIPT_PATH.parents[3]
BACKEND_ROOT = SOURCE_ROOT / "backend"
if not BACKEND_ROOT.is_dir():
    BACKEND_ROOT = SOURCE_ROOT / "source" / "backend"
if not BACKEND_ROOT.is_dir():
    raise SystemExit("competition backend source is unavailable")
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, event, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from competition_runtime import slurm_probe_script, slurm_user  # noqa: E402
from database import Base  # noqa: E402
from models import User  # noqa: E402
from models_workflow import (  # noqa: E402
    WorkflowAttempt,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
)
from services.competition_reconcile import (  # noqa: E402
    CompetitionReconciler,
    ReconcileError,
)
from services.competition_slurm import (  # noqa: E402
    SlurmBinaries,
    SlurmClient,
    SlurmSubmission,
)


PROBE_SCRIPT = slurm_probe_script()
SLURM_USER = slurm_user()
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})
EXPECTED_EVENTS = frozenset(
    {
        "submission_accepted",
        "submission_failed",
        "cancellation_requested",
        "scheduler_state_changed",
    }
)


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def run_command(label: str, argv: list[str], *, check: bool = False) -> dict[str, object]:
    completed = subprocess.run(
        argv,
        shell=False,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
    )
    if len(completed.stdout) > MAX_OUTPUT_BYTES or len(completed.stderr) > MAX_OUTPUT_BYTES:
        raise RuntimeError(f"{label} output exceeded the evidence limit")
    command_root = EVIDENCE_ROOT / "scheduler"
    command_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    stdout_path = command_root / f"{label}.stdout"
    stderr_path = command_root / f"{label}.stderr"
    stdout_path.write_bytes(completed.stdout)
    stderr_path.write_bytes(completed.stderr)
    stdout_path.chmod(0o600)
    stderr_path.chmod(0o600)
    result = {
        "argv": argv,
        "returncode": completed.returncode,
        "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
    }
    write_json(command_root / f"{label}.json", result)
    if check and completed.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}")
    return {
        **result,
        "stderr": completed.stderr.decode("utf-8", errors="replace").strip(),
        "stdout": completed.stdout.decode("utf-8", errors="replace").strip(),
    }


def create_client(*, sbatch: str = "/usr/bin/sbatch") -> SlurmClient:
    return SlurmClient(
        binaries=SlurmBinaries(sbatch=sbatch),
        workflow_root=WORKFLOW_ROOT,
        allowed_scripts=(PROBE_SCRIPT,),
    )


def create_reconciler(*, sbatch: str = "/usr/bin/sbatch") -> CompetitionReconciler:
    return CompetitionReconciler(
        slurm=create_client(sbatch=sbatch),
        probe_script=PROBE_SCRIPT,
        slurm_user=SLURM_USER,
    )


def add_workflow(session: Session, owner_id: int, label: str) -> str:
    workflow_id = str(uuid.uuid4())
    session.add(
        WorkflowRun(
            id=workflow_id,
            owner_id=owner_id,
            template_version="stage6_probe_v1",
            material=f"stage6-{label}",
            source_kind="probe",
            status="validated",
            input_sha256=hashlib.sha256(label.encode("ascii")).hexdigest(),
            release_commit=os.environ.get("LMATELAB_GIT_COMMIT", "0" * 40),
            metadata_json={"stage6_smoke": label},
        )
    )
    session.flush()
    session.add(
        WorkflowStep(
            workflow_id=workflow_id,
            step_key="relax",
            position=0,
            status="waiting",
            parameters_json={},
        )
    )
    session.add(
        WorkflowEvent(
            workflow_id=workflow_id,
            sequence=1,
            event_type="workflow_validated",
            payload_json={"stage6_smoke": label},
        )
    )
    session.commit()
    return workflow_id


def reconcile_until(attempt_id: str, expected: str) -> list[dict[str, object]]:
    deadline = time.monotonic() + PROBE_TIMEOUT_SECONDS
    observations: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        # A fresh object and session exercise restart-safe database reconciliation.
        reconciler = create_reconciler()
        with Session(ENGINE) as session:
            outcome = reconciler.reconcile_attempt(session, attempt_id)
        observations.append(asdict(outcome))
        if outcome.status in TERMINAL_STATES:
            if outcome.status != expected:
                raise RuntimeError(
                    f"attempt {attempt_id} ended as {outcome.status}, expected {expected}"
                )
            return observations
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"attempt {attempt_id} did not reach {expected}")


def capture_job(job_id: str, label: str) -> None:
    for source, argv in (
        ("squeue", ["/usr/bin/squeue", "--json", f"--jobs={job_id}"]),
        ("scontrol", ["/usr/bin/scontrol", "--json", "show", "job", job_id]),
        ("sacct", ["/usr/bin/sacct", "--json", f"--jobs={job_id}"]),
    ):
        run_command(f"{label}-{source}", argv)


def test_only_probe() -> dict[str, object]:
    client = create_client()
    workflow_id = str(uuid.uuid4())
    attempt_id = str(uuid.uuid4())
    attempt_directory = client.prepare_attempt_directory(workflow_id, attempt_id)
    submission = SlurmSubmission(
        workflow_id=workflow_id,
        attempt_id=attempt_id,
        step_key="relax",
        attempt_number=1,
        attempt_directory=attempt_directory,
        script_path=PROBE_SCRIPT,
        probe_mode="success",
    )
    result = client.test_submission(submission)
    queue = run_command(
        "test-only-squeue",
        ["/usr/bin/squeue", "--json", f"--name={submission.job_name}"],
        check=True,
    )
    payload = json.loads(str(queue["stdout"]))
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise RuntimeError("test-only queue evidence has no jobs list")
    if any(isinstance(row, dict) and row.get("name") == submission.job_name for row in jobs):
        raise RuntimeError("sbatch --test-only left a residual job")
    return {
        "job_name": submission.job_name,
        "returncode": result.returncode,
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
    }


def controlled_submission_failure(owner_id: int) -> str:
    with Session(ENGINE) as session:
        workflow_id = add_workflow(session, owner_id, "submission-failed")
    try:
        with Session(ENGINE) as session:
            create_reconciler(sbatch="/usr/bin/false").submit_probe(
                session, workflow_id, "success"
            )
    except ReconcileError as exc:
        if exc.code != "submission_failed":
            raise
    else:
        raise RuntimeError("controlled scheduler rejection was unexpectedly accepted")
    return workflow_id


def run_probe(owner_id: int, mode: str, expected: str) -> dict[str, object]:
    with Session(ENGINE) as session:
        workflow_id = add_workflow(session, owner_id, mode)
    with Session(ENGINE) as session:
        submission = create_reconciler().submit_probe(session, workflow_id, mode)
    OWNED_JOB_IDS.add(submission.job_id)

    cancellation = None
    if mode == "cancel":
        with Session(ENGINE) as session:
            cancellation = asdict(
                create_reconciler().cancel_attempt(
                    session, workflow_id, submission.attempt_id
                )
            )
    observations = reconcile_until(submission.attempt_id, expected)
    capture_job(submission.job_id, mode)
    return {
        "cancellation": cancellation,
        "observations": observations,
        "submission": asdict(submission),
    }


def non_owned_rejection(owner_id: int) -> dict[str, object]:
    foreign_directory = EVIDENCE_ROOT / "foreign-control"
    foreign_directory.mkdir(mode=0o700)
    foreign_workflow_id = str(uuid.uuid4())
    foreign_attempt_id = str(uuid.uuid4())
    submitted = run_command(
        "foreign-submit",
        [
            "/usr/bin/sbatch",
            "--parsable",
            f"--job-name=stage6-foreign-{SLURM_JOB_ID}",
            f"--comment=stage6-foreign-control:{SLURM_JOB_ID}",
            f"--chdir={foreign_directory}",
            f"--output={foreign_directory / 'stdout.log'}",
            f"--error={foreign_directory / 'stderr.log'}",
            str(PROBE_SCRIPT),
            "cancel",
            foreign_workflow_id,
            foreign_attempt_id,
        ],
        check=True,
    )
    match = re.fullmatch(r"([1-9][0-9]*)(?:;[A-Za-z0-9_.-]+)?", str(submitted["stdout"]))
    if match is None:
        raise RuntimeError("foreign control submission returned an invalid job id")
    job_id = match.group(1)
    OWNED_JOB_IDS.add(job_id)

    with Session(ENGINE) as session:
        workflow_id = add_workflow(session, owner_id, "foreign-rejection")
        step = session.scalar(
            select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id)
        )
        if step is None:
            raise RuntimeError("foreign rejection workflow has no step")
        run = session.get(WorkflowRun, workflow_id)
        run.status = "queued"
        step.status = "queued"
        attempt = WorkflowAttempt(
            id=foreign_attempt_id,
            step_id=step.id,
            attempt_number=1,
            status="queued",
            slurm_job_id=job_id,
            working_directory=str(
                create_client().prepare_attempt_directory(workflow_id, foreign_attempt_id)
            ),
            metadata_json={
                "comment": (
                    f"lmatelab:workflow={workflow_id};attempt={foreign_attempt_id}"
                ),
                "job_name": f"lmatelab-{workflow_id[:8]}-relax-a1",
                "probe_mode": "cancel",
            },
        )
        session.add(attempt)
        session.commit()

    deadline = time.monotonic() + 30
    while True:
        try:
            with Session(ENGINE) as session:
                create_reconciler().cancel_attempt(session, workflow_id, foreign_attempt_id)
        except ReconcileError as exc:
            if exc.code == "cancellation_ownership_mismatch":
                rejection = {"code": exc.code, "job_id": job_id}
                break
            if exc.code != "scheduler_unavailable" or time.monotonic() >= deadline:
                raise
            time.sleep(POLL_SECONDS)
        else:
            raise RuntimeError("non-owned scheduler job passed the cancellation gate")

    run_command("foreign-cleanup", ["/usr/bin/scancel", job_id], check=True)
    capture_job(job_id, "foreign")
    return rejection


def snapshot_ledger() -> dict[str, object]:
    with Session(ENGINE) as session:
        attempts = session.scalars(select(WorkflowAttempt).order_by(WorkflowAttempt.created_at)).all()
        events = session.scalars(
            select(WorkflowEvent).order_by(WorkflowEvent.workflow_id, WorkflowEvent.sequence)
        ).all()
        event_rows = [
            {
                "created_at": row.created_at.isoformat(),
                "event_type": row.event_type,
                "payload": json.loads(row.payload_json),
                "sequence": row.sequence,
                "workflow_id": row.workflow_id,
            }
            for row in events
        ]
        counts = {
            event_type: sum(row.event_type == event_type for row in events)
            for event_type in sorted(EXPECTED_EVENTS)
        }
        missing = sorted(event_type for event_type, count in counts.items() if count < 1)
        if missing:
            raise RuntimeError(f"required ledger events are missing: {missing}")
        return {
            "attempts": [
                {
                    "attempt_id": row.id,
                    "job_id": row.slurm_job_id,
                    "metadata": json.loads(row.metadata_json),
                    "status": row.status,
                }
                for row in attempts
            ],
            "event_counts": counts,
            "events": event_rows,
        }


def write_manifest() -> None:
    entries = []
    for path in sorted(EVIDENCE_ROOT.rglob("*")):
        if path.is_file() and path.name != "manifest.sha256":
            relative = path.relative_to(EVIDENCE_ROOT).as_posix()
            entries.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
    manifest = EVIDENCE_ROOT / "manifest.sha256"
    manifest.write_text("\n".join(entries) + "\n", encoding="ascii")
    manifest.chmod(0o600)


def cleanup_jobs() -> None:
    for job_id in sorted(OWNED_JOB_IDS, key=int):
        try:
            subprocess.run(
                ["/usr/bin/scancel", job_id],
                shell=False,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def main() -> None:
    if EVIDENCE_ROOT.exists():
        raise SystemExit(f"evidence directory already exists: {EVIDENCE_ROOT}")
    EVIDENCE_ROOT.mkdir(mode=0o700, parents=True)
    WORKFLOW_ROOT.mkdir(mode=0o700)
    if not PROBE_SCRIPT.is_file():
        raise SystemExit(f"fixed probe script is missing: {PROBE_SCRIPT}")

    Base.metadata.create_all(ENGINE)
    with Session(ENGINE) as session:
        owner = User(
            email=f"stage6-smoke-{SLURM_JOB_ID}@invalid.local",
            password_hash="not-a-login-account",
            name=f"stage6-smoke-{SLURM_JOB_ID}",
            alias="stage6-smoke",
            role="operator",
        )
        session.add(owner)
        session.commit()
        owner_id = owner.id

    summary = {
        "compute_job_id": SLURM_JOB_ID,
        "compute_node": os.environ.get("SLURMD_NODENAME", os.environ.get("HOSTNAME")),
        "database": DATABASE_PATH.name,
        "probe_script": str(PROBE_SCRIPT),
        "slurm_user": SLURM_USER,
        "test_only": test_only_probe(),
        "controlled_submission_failure_workflow": controlled_submission_failure(owner_id),
        "success": run_probe(owner_id, "success", "succeeded"),
        "fail": run_probe(owner_id, "fail", "failed"),
        "cancel": run_probe(owner_id, "cancel", "cancelled"),
        "non_owned_rejection": non_owned_rejection(owner_id),
    }
    summary["ledger"] = snapshot_ledger()
    with sqlite3.connect(DATABASE_PATH) as connection:
        integrity_check = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity_check != "ok":
        raise RuntimeError(f"SQLite integrity_check failed: {integrity_check}")
    summary["integrity_check"] = integrity_check
    write_json(EVIDENCE_ROOT / "summary.json", summary)


OWNED_JOB_IDS: set[str] = set()
ENGINE = create_engine(f"sqlite:///{DATABASE_PATH}")


@event.listens_for(ENGINE, "connect")
def configure_sqlite(connection, _record) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=5000")


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        if EVIDENCE_ROOT.is_dir():
            write_json(
                EVIDENCE_ROOT / "failure.json",
                {"error_type": type(exc).__name__, "message": str(exc)},
            )
        raise
    finally:
        cleanup_jobs()
        ENGINE.dispose()
        if EVIDENCE_ROOT.is_dir():
            write_manifest()
