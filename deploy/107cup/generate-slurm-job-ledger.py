from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


LOG_NAME = re.compile(r"^(?P<kind>.+)-(?P<job_id>\d+)\.(?P<stream>out|err)$")
SCONTROL_LINE = re.compile(r"\bJobId=(?P<job_id>\d+)\s+JobName=")
CANCEL_LINE = re.compile(
    r"\[(?P<at>[^]]+)]\s+error:\s+\*\*\* JOB (?P<job_id>\d+) ON "
    r"(?P<node>\S+) CANCELLED"
)

FIELDS = (
    "job_id",
    "function_group",
    "job_kind",
    "purpose",
    "scheduler_result",
    "scheduler_evidence",
    "exit_code",
    "functional_result",
    "scientific_result",
    "scientific_reason",
    "material",
    "workflow_step",
    "workflow_id",
    "partition",
    "node",
    "cpus",
    "memory",
    "gpus",
    "submitted_at",
    "started_at",
    "finished_at",
    "queue_seconds",
    "run_seconds",
    "vasp_wall_seconds",
    "peak_rss_kbytes",
    "stdout_bytes",
    "stderr_bytes",
    "stdout_sha256",
    "stderr_sha256",
    "evidence_files",
    "notes",
)

FUNCTION_GROUPS = {
    "build": ("build_and_release", "Build, test, and publish an immutable release"),
    "preview-build": ("build_and_release", "Build an isolated frontend preview"),
    "workflow-preview-build": (
        "build_and_release",
        "Build an isolated workflow frontend preview",
    ),
    "service": ("web_service", "Run the long-lived FastAPI and frontend service"),
    "preview-service": ("web_service", "Run an isolated frontend preview service"),
    "workflow-preview-service": (
        "web_service",
        "Run an isolated workflow preview service",
    ),
    "preview-snapshot": (
        "snapshot_and_provenance",
        "Capture database, release, service, and scheduler evidence",
    ),
    "rollback-smoke": ("recovery_and_rollback", "Exercise isolated release rollback"),
    "viewer-baseline": ("access_and_roles", "Run Viewer baseline authorization tests"),
    "viewer-tests": ("access_and_roles", "Run Viewer authorization tests"),
    "provision-viewer": ("access_and_roles", "Provision the Demo Viewer identity"),
    "operator-acceptance-test": (
        "access_and_roles",
        "Run Operator and Viewer authorization acceptance tests",
    ),
    "public-write-test": (
        "access_and_roles",
        "Verify the public Operator write-route allowlist",
    ),
    "stage6-smoke": ("slurm_adapter", "Exercise the real Slurm adapter"),
    "stage7-preflight": ("vasp_preflight", "Verify VASP and VASPKIT prerequisites"),
    "generic-vaspkit-preflight": (
        "vasp_preflight",
        "Verify VASPKIT 103 POTCAR and 302 band-path generation",
    ),
    "stage7-acceptance": ("vasp_workflow_control", "Create or inspect Stage 7 workflows"),
    "stage7-terminal-diagnostic": (
        "vasp_workflow_control",
        "Diagnose Stage 7 workflow finalization",
    ),
    "stage8-acceptance": (
        "results_and_evidence",
        "Validate structure, BAND, DOS, and evidence bundles",
    ),
    "stage10-acceptance": (
        "delivery_acceptance",
        "Run read-only delivery acceptance",
    ),
    "cancel-unstarted": (
        "workflow_cancellation",
        "Validate cancellation before the first scheduler submission",
    ),
    "python-diagnostic": ("environment_probe", "Inspect compute-node Python tooling"),
    "virtualenv-probe": ("environment_probe", "Probe virtual environment creation"),
    "pip-bootstrap-probe": ("environment_probe", "Probe pip bootstrap"),
    "module-probe": ("environment_probe", "Probe the site Python module"),
    "miniconda-probe": ("environment_probe", "Probe an isolated Miniconda environment"),
    "memfd-probe": ("slurm_diagnostic", "Probe memfd submission-script handling"),
    "otmpfile-probe": ("slurm_diagnostic", "Probe O_TMPFILE submission-script handling"),
    "generic-contract-tests": (
        "test_and_diagnostic",
        "Run generic workflow contract tests",
    ),
    "generic-fix-tests": ("test_and_diagnostic", "Run focused generic workflow fixes"),
    "backend-full-fix": ("test_and_diagnostic", "Run the full backend fix suite"),
}

FAILURE_REASONS = {
    32598: "base Python executable could not create the required environment",
    32599: "compute-node Python diagnostic found pip unavailable",
    33979: "release manifest was missing; failure did not switch current",
    33998: "rollback drill lacked the synthetic Operator fixture",
    34001: "controlled termination status was propagated by the rollback drill",
    36592: "snapshot could not obtain the expected scheduler evidence",
    36596: "snapshot could not reach the target service",
    37391: "workflow preview build stopped before the release verification marker",
    37689: "backend build tests failed",
    37713: "candidate service was allocated to a node whose port was already in use",
    38598: "Stage 6 smoke could not resolve the release backend from the Slurm spool",
    40053: "backend build tests failed",
    40054: "memfd probe could not recover the submission-script snapshot",
    40079: "candidate service port was already in use",
    40087: "post-snapshot detected an expected current-target change",
    40096: "backend build tests failed",
    40253: "Stage 7 acceptance could not import competition_runtime",
    40269: "diagnostic wrapper omitted LMATELAB_FRONTEND_DIST",
    40270: "diagnostic exposed duplicate workflow event sequencing and then exited nonzero",
    40304: "Stage 8 acceptance hit an SQLAlchemy mapper initialization error",
    40306: "Stage 8 acceptance rejected an unparseable scientific artifact",
    40784: "candidate service port was already in use",
    41039: "service recovery build fixture lacked service-state.json",
    41064: "cross-platform delivery manifest hash test failed",
    41680: "post-snapshot used a pre-deploy invariant after an intentional release change",
    46081: "preflight exposed incorrect rejection of VASPKIT recommended W_sv",
    46092: "sbatch --wrap used /bin/sh, which rejected pipefail",
    46093: "tests exposed missing 8 KiB bounds for VASPKIT 302 metadata",
    46098: "generic workflow build tests failed before release publication",
    50529: "cancellation wrapper omitted LMATELAB_FRONTEND_DIST",
}

DOCUMENTED_RUNTIME_SECONDS = {
    38621: 42,
    38623: 8,
    40272: 65,
    40274: 1,
    46103: 17,
    46104: 37,
    46105: 97,
    46109: 41,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _seconds(value: str) -> int | None:
    if not value or value in {"N/A", "Unknown", "None"}:
        return None
    days = 0
    clock = value
    if "-" in value:
        raw_days, clock = value.split("-", 1)
        days = int(raw_days)
    parts = [int(part) for part in clock.split(":")]
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = 0, parts[0], parts[1]
    else:
        return None
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _parse_time(value: str) -> datetime | None:
    if not value or value in {"N/A", "Unknown", "None"}:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration(start: str, finish: str) -> float | str:
    left = _parse_time(start)
    right = _parse_time(finish)
    if left is None or right is None:
        return ""
    if left.tzinfo is None and right.tzinfo is not None:
        right = right.replace(tzinfo=None)
    if left.tzinfo is not None and right.tzinfo is None:
        left = left.replace(tzinfo=None)
    return max(0.0, round((right - left).total_seconds(), 3))


def _parse_key_values(line: str) -> dict[str, str]:
    return dict(re.findall(r"(?<!\S)([A-Za-z][A-Za-z0-9_]*?)=(\S+)", line))


def _load_scontrol_snapshots(evidence_dir: Path) -> dict[int, dict[str, str]]:
    snapshots: dict[int, dict[str, str]] = {}
    for path in evidence_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".out", ".slurm"}:
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        text = _read_text(path)
        for line in text.splitlines():
            match = SCONTROL_LINE.search(line)
            if not match:
                continue
            job_id = int(match.group("job_id"))
            values = _parse_key_values(line)
            values["evidence_file"] = path.relative_to(evidence_dir.parent).as_posix()
            current = snapshots.get(job_id)
            if current is None or values.get("JobState") in {"COMPLETED", "FAILED", "CANCELLED"}:
                snapshots[job_id] = values
    return snapshots


def _load_stage6_children(evidence_dir: Path) -> list[dict[str, object]]:
    scheduler = evidence_dir / "stage6" / "job-38623" / "scheduler"
    rows = []
    for label, job_id in (("success", 38625), ("fail", 38626), ("cancel", 38627), ("foreign", 38628)):
        path = scheduler / f"{label}-scontrol.stdout"
        payload = json.loads(path.read_text(encoding="utf-8"))
        job = payload["jobs"][0]
        state = job["job_state"][0].lower()
        exit_code = job["exit_code"]["return_code"]["number"]
        signal = job["exit_code"]["signal"]["id"]["number"]
        submit_epoch = job["submit_time"]["number"]
        start_epoch = job["start_time"]["number"]
        end_epoch = job["end_time"]["number"]
        iso = lambda value: datetime.fromtimestamp(value, timezone.utc).isoformat()
        rows.append(
            {
                "job_id": job_id,
                "function_group": "slurm_adapter",
                "job_kind": "stage6-child-probe",
                "purpose": {
                    "success": "Real successful Slurm adapter probe",
                    "fail": "Intentional nonzero-exit Slurm adapter probe",
                    "cancel": "Owned-job cancellation probe",
                    "foreign": "Non-owned cancellation rejection control",
                }[label],
                "scheduler_result": state,
                "scheduler_evidence": "saved_scontrol_json",
                "exit_code": f"{exit_code}:{signal}",
                "functional_result": {
                    "success": "passed",
                    "fail": "expected_failure_observed",
                    "cancel": "expected_cancellation_observed",
                    "foreign": "ownership_rejection_observed_then_harness_cleanup",
                }[label],
                "scientific_result": "not_applicable",
                "partition": job["partition"],
                "node": job.get("nodes") or "",
                "cpus": job["cpus"]["number"],
                "memory": f'{job["memory_per_node"]["number"]}M',
                "gpus": 0,
                "submitted_at": iso(submit_epoch),
                "started_at": iso(start_epoch),
                "finished_at": iso(end_epoch),
                "queue_seconds": max(0, start_epoch - submit_epoch),
                "run_seconds": max(0, end_epoch - start_epoch),
                "evidence_files": ";".join(
                    (
                        path.relative_to(evidence_dir.parent).as_posix(),
                        (scheduler.parent / "summary.json").relative_to(evidence_dir.parent).as_posix(),
                    )
                ),
                "notes": "Stage 6 child job; not duplicated in root logs",
            }
        )
    return rows


def _base_row() -> dict[str, object]:
    return {field: "" for field in FIELDS}


def _root_rows(logs_dir: Path, evidence_dir: Path) -> list[dict[str, object]]:
    grouped: dict[tuple[int, str], dict[str, Path]] = defaultdict(dict)
    for path in logs_dir.iterdir():
        if not path.is_file():
            continue
        match = LOG_NAME.match(path.name)
        if match:
            grouped[(int(match.group("job_id")), match.group("kind"))][match.group("stream")] = path

    snapshots = _load_scontrol_snapshots(evidence_dir)
    rows = []
    for (job_id, kind), streams in sorted(grouped.items()):
        row = _base_row()
        group, purpose = FUNCTION_GROUPS.get(kind, ("test_and_diagnostic", kind.replace("-", " ")))
        stdout = streams.get("out")
        stderr = streams.get("err")
        out_text = _read_text(stdout) if stdout else ""
        err_text = _read_text(stderr) if stderr else ""
        combined = out_text + "\n" + err_text
        snapshot = snapshots.get(job_id, {})
        cancellation = CANCEL_LINE.search(err_text)

        if job_id == 54176:
            scheduler_result = "running"
            scheduler_evidence = "live_scontrol_2026-09-05T10:56:22+08:00"
            functional_result = "healthy_running"
        elif cancellation:
            scheduler_result = "cancelled"
            scheduler_evidence = "slurmd_cancellation_record"
            functional_result = (
                "passed_then_controlled_stop"
                if group == "web_service"
                else "cancelled_before_completion"
            )
        elif job_id in FAILURE_REASONS:
            scheduler_result = "failed"
            scheduler_evidence = (
                "saved_scontrol" if snapshot.get("JobState") == "FAILED" else "terminal_job_log"
            )
            functional_result = "failed"
        else:
            scheduler_result = "completed"
            scheduler_evidence = (
                "saved_scontrol"
                if snapshot.get("JobState") == "COMPLETED"
                else "successful_terminal_job_log"
            )
            functional_result = "passed"

        exit_code = snapshot.get("ExitCode", "")
        if not exit_code:
            if scheduler_result == "completed":
                exit_code = "0:0_by_terminal_evidence"
            elif scheduler_result == "failed":
                exit_code = "nonzero_by_terminal_evidence"

        row.update(
            {
                "job_id": job_id,
                "function_group": group,
                "job_kind": kind,
                "purpose": purpose,
                "scheduler_result": scheduler_result,
                "scheduler_evidence": scheduler_evidence,
                "exit_code": exit_code,
                "functional_result": functional_result,
                "scientific_result": "not_applicable",
                "partition": snapshot.get("Partition", ""),
                "node": snapshot.get("NodeList", "") if snapshot.get("NodeList") != "(null)" else "",
                "cpus": snapshot.get("NumCPUs", ""),
                "submitted_at": snapshot.get("SubmitTime", ""),
                "started_at": snapshot.get("StartTime", ""),
                "finished_at": snapshot.get("EndTime", "") if scheduler_result != "running" else "",
                "queue_seconds": _duration(
                    snapshot.get("SubmitTime", ""), snapshot.get("StartTime", "")
                ),
                "run_seconds": _seconds(snapshot.get("RunTime", "")) or "",
                "stdout_bytes": stdout.stat().st_size if stdout else 0,
                "stderr_bytes": stderr.stat().st_size if stderr else 0,
                "stdout_sha256": _sha256(stdout) if stdout else "",
                "stderr_sha256": _sha256(stderr) if stderr else "",
                "evidence_files": ";".join(
                    path.relative_to(logs_dir.parent).as_posix()
                    for path in (stdout, stderr)
                    if path is not None
                ),
                "notes": FAILURE_REASONS.get(job_id, ""),
            }
        )
        if cancellation:
            row["finished_at"] = cancellation.group("at")
            row["node"] = cancellation.group("node")
            row["run_seconds"] = _duration(row["started_at"], row["finished_at"])
        if job_id in DOCUMENTED_RUNTIME_SECONDS and not row["run_seconds"]:
            row["run_seconds"] = DOCUMENTED_RUNTIME_SECONDS[job_id]
            row["scheduler_evidence"] += "+project_evidence_document"
        if job_id == 54176:
            row.update(
                {
                    "partition": "P107-A100",
                    "node": "anode18",
                    "cpus": 2,
                    "memory": "8G",
                    "gpus": 0,
                    "submitted_at": "2026-09-05T10:56:02+08:00",
                    "started_at": "2026-09-05T10:56:02+08:00",
                    "queue_seconds": 0,
                    "run_seconds": "running_at_snapshot",
                    "notes": "Automatic service recovery submission; healthy at the audit snapshot",
                }
            )
        rows.append(row)
    return rows


def _vasp_rows(path: Path) -> list[dict[str, object]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for source in csv.DictReader(handle):
            row = _base_row()
            raw_state = source["scheduler_raw_state"].lower()
            accepted = source["scientific_accepted"]
            if raw_state == "completed":
                scheduler_result = "completed"
            elif raw_state == "failed":
                scheduler_result = "failed"
            elif raw_state == "cancelled":
                scheduler_result = "cancelled"
            else:
                scheduler_result = source["scheduler_state"] or "unknown"
            scientific_result = (
                "accepted"
                if accepted == "true"
                else "rejected"
                if accepted == "false"
                else "not_evaluated"
            )
            functional_result = (
                "passed"
                if scheduler_result == "completed" and scientific_result == "accepted"
                else "scheduler_failed"
                if scheduler_result == "failed"
                else "scientific_gate_failed"
            )
            row.update(
                {
                    "job_id": source["job_id"],
                    "function_group": "vasp_calculation",
                    "job_kind": source["category"],
                    "purpose": f'{source["material"]} {source["step"].upper()} calculation',
                    "scheduler_result": scheduler_result,
                    "scheduler_evidence": "database_saved_scontrol_observation",
                    "exit_code": source["exit_code"],
                    "functional_result": functional_result,
                    "scientific_result": scientific_result,
                    "scientific_reason": source["scientific_reason"],
                    "material": source["material"],
                    "workflow_step": source["step"],
                    "workflow_id": source["workflow_id"],
                    "partition": "P107-RTX5090",
                    "node": source["node"],
                    "cpus": 16,
                    "memory": "32G",
                    "gpus": "1xRTX5090",
                    "submitted_at": source["submitted_at"],
                    "started_at": source["started_at"],
                    "finished_at": source["finished_at"],
                    "queue_seconds": source["queue_seconds"],
                    "run_seconds": source["run_seconds"],
                    "vasp_wall_seconds": source["vasp_wall_seconds"],
                    "peak_rss_kbytes": source["peak_rss_kbytes"],
                    "evidence_files": source["working_directory"],
                    "notes": (
                        f'attempt={source["attempt_id"]}; release={source["release_commit"]}; '
                        f'runtime={source["runtime_evidence"]}'
                    ),
                }
            )
            rows.append(row)
    return rows


def _stage7_terminal_row(evidence_dir: Path) -> dict[str, object]:
    row = _base_row()
    stdout = evidence_dir / "stage7" / "terminal-40274.out"
    stderr = evidence_dir / "stage7" / "terminal-40274.err"
    row.update(
        {
            "job_id": 40274,
            "function_group": "vasp_workflow_control",
            "job_kind": "stage7-terminal-verification",
            "purpose": "Read-only verification of the intentional Stage 7 failure chain",
            "scheduler_result": "completed",
            "scheduler_evidence": "project_evidence_document+terminal_job_log",
            "exit_code": "0:0",
            "functional_result": "passed",
            "scientific_result": "not_applicable",
            "partition": "P107-A100",
            "node": "anode16",
            "queue_seconds": "unavailable",
            "run_seconds": 1,
            "stdout_bytes": stdout.stat().st_size,
            "stderr_bytes": stderr.stat().st_size,
            "stdout_sha256": _sha256(stdout),
            "stderr_sha256": _sha256(stderr),
            "evidence_files": ";".join(
                (
                    stdout.relative_to(evidence_dir.parent).as_posix(),
                    stderr.relative_to(evidence_dir.parent).as_posix(),
                )
            ),
            "notes": "This job wrote only to evidence/stage7, so it is absent from root logs",
        }
    )
    return row


def generate(logs_dir: Path, evidence_dir: Path, vasp_ledger: Path, output: Path) -> None:
    for path in (logs_dir, evidence_dir):
        if not path.is_dir():
            raise RuntimeError(f"missing input directory: {path}")
    if not vasp_ledger.is_file():
        raise RuntimeError(f"missing VASP ledger: {vasp_ledger}")

    rows = _root_rows(logs_dir, evidence_dir)
    rows.extend(_load_stage6_children(evidence_dir))
    rows.extend(_vasp_rows(vasp_ledger))
    rows.append(_stage7_terminal_row(evidence_dir))
    rows.sort(key=lambda row: int(row["job_id"]))

    job_ids = [int(row["job_id"]) for row in rows]
    if len(rows) != 218 or len(job_ids) != len(set(job_ids)):
        raise RuntimeError(
            f"expected 218 unique jobs, got rows={len(rows)} unique={len(set(job_ids))}"
        )
    excluded = {38285, 73001, 30121, 30147}
    if excluded.intersection(job_ids):
        raise RuntimeError(f"excluded non-project/test jobs entered ledger: {excluded.intersection(job_ids)}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--vasp-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate(args.logs_dir, args.evidence_dir, args.vasp_ledger, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
