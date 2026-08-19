from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from competition_runtime import release_commit, workflow_root
from database import engine
from models_workflow import WorkflowRun, WorkflowStep, canonical_json
from services.competition_results import CompetitionResultService


SUCCESS_WORKFLOW_ID = "4b566547-961b-4e10-a8d0-99431f2e2229"
FAILURE_WORKFLOW_ID = "db9c793d-cf8f-4207-823b-5943d825f21d"
SUCCESS_JOBS = ["40212", "40250", "40251", "40252"]
FAILURE_JOBS = ["40264", "40265", None, None]
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_run(session: Session, workflow_id: str) -> WorkflowRun:
    run = session.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.id == workflow_id)
        .options(
            selectinload(WorkflowRun.owner),
            selectinload(WorkflowRun.steps).selectinload(WorkflowStep.attempts),
            selectinload(WorkflowRun.files),
            selectinload(WorkflowRun.events),
        )
    )
    if run is None:
        raise RuntimeError(f"required workflow is missing: {workflow_id}")
    return run


def _assert_jobs(detail: dict, expected: list[str | None]) -> None:
    actual = [step.get("job_id") for step in detail.get("steps", [])]
    if actual != expected:
        raise RuntimeError(f"workflow Job ledger changed: {actual!r}")


def _write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Stage 8 acceptance must run through Slurm")
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    service = CompetitionResultService(workflow_root=workflow_root())

    with Session(engine) as session:
        session.connection().exec_driver_sql("PRAGMA query_only=ON")
        success_run = _load_run(session, SUCCESS_WORKFLOW_ID)
        failure_run = _load_run(session, FAILURE_WORKFLOW_ID)
        success = service.detail(success_run)
        failure = service.detail(failure_run)
        if success.get("status") != "succeeded" or "vasp_detail" not in success:
            raise RuntimeError(f"success workflow did not parse: {success.get('failure_evidence')}")
        if failure.get("status") != "failed" or "vasp_detail" in failure:
            raise RuntimeError("failure workflow exposed a scientific success detail")
        if failure.get("failure_evidence", {}).get("reason") != "electronic_not_converged":
            raise RuntimeError("controlled failure reason changed")
        _assert_jobs(success, SUCCESS_JOBS)
        _assert_jobs(failure, FAILURE_JOBS)

        plots = {kind: service.plot(success_run, kind) for kind in ("band", "dos")}
        for kind, plot in plots.items():
            image = base64.b64decode(plot["image_base64"], validate=True)
            if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError(f"{kind} plot is not a PNG")

        scientific = {
            kind: service.artifact(session, success_run, kind)
            for kind in ("structure-cif", "structure-poscar", "band-data", "dos-data")
        }
        if not scientific["structure-cif"].content.startswith(b"data_"):
            raise RuntimeError("CIF export is invalid")
        if not scientific["structure-poscar"].content.strip():
            raise RuntimeError("POSCAR export is empty")
        if not scientific["band-data"].content.startswith(b"# band.dat"):
            raise RuntimeError("BAND data export is invalid")
        if not scientific["dos-data"].content.startswith(b"PK"):
            raise RuntimeError("DOS data export is not a ZIP")

        success_bundle = service.artifact(session, success_run, "evidence-bundle")
        repeated_bundle = service.artifact(session, success_run, "evidence-bundle")
        failure_bundle = service.artifact(session, failure_run, "evidence-bundle")
        if success_bundle.content != repeated_bundle.content:
            raise RuntimeError("success evidence bundle is not deterministic")
        for bundle, workflow_id in (
            (success_bundle, SUCCESS_WORKFLOW_ID),
            (failure_bundle, FAILURE_WORKFLOW_ID),
        ):
            payload = json.loads(bundle.content)
            if payload.get("schema") != "lmatelab-107cup-evidence-v1":
                raise RuntimeError("evidence bundle schema changed")
            if payload.get("workflow", {}).get("id") != workflow_id:
                raise RuntimeError("evidence bundle identity changed")
            if _SHA256_RE.fullmatch(payload.get("payload_sha256", "")) is None:
                raise RuntimeError("evidence bundle digest is invalid")

        summary = {
            "schema": "lmatelab-107cup-stage8-acceptance-v1",
            "slurm_job_id": os.environ["SLURM_JOB_ID"],
            "node": os.environ.get("SLURMD_NODENAME", os.environ.get("HOSTNAME")),
            "release_commit": release_commit(),
            "success_workflow": SUCCESS_WORKFLOW_ID,
            "failure_workflow": FAILURE_WORKFLOW_ID,
            "success_jobs": SUCCESS_JOBS,
            "failure_jobs": FAILURE_JOBS,
            "bandgap_eV": success["vasp_detail"]["properties"]["bandgap_eV"],
            "energy_eV": success["vasp_detail"]["row"]["energy"],
            "artifacts": {
                kind: {"size_bytes": len(item.content), "sha256": _sha256(item.content)}
                for kind, item in scientific.items()
            },
            "plots": {
                kind: {
                    "png_size_bytes": len(base64.b64decode(item["image_base64"])),
                    "source_sha256": item["provenance"]["sha256"],
                }
                for kind, item in plots.items()
            },
            "success_bundle_sha256": _sha256(success_bundle.content),
            "failure_bundle_sha256": _sha256(failure_bundle.content),
        }
        summary_bytes = canonical_json(summary).encode("utf-8") + b"\n"
        _write_private(output_dir / "summary.json", summary_bytes)
        _write_private(output_dir / "success-evidence-bundle.json", success_bundle.content)
        _write_private(output_dir / "failure-evidence-bundle.json", failure_bundle.content)
        entries = []
        for path in sorted(output_dir.iterdir()):
            entries.append(f"{_sha256(path.read_bytes())}  {path.name}")
        _write_private(
            output_dir / "manifest.sha256",
            ("\n".join(entries) + "\n").encode("ascii"),
        )
        session.rollback()

    print(canonical_json(summary))
    print("STAGE8_ACCEPTANCE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
