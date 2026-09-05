from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath


STAGE10_MANIFEST_PATHS = (
    ".gitattributes",
    "backend/auth.py",
    "backend/auth_identity.py",
    "backend/competition_templates/pbe_2d_v1/INCAR.band",
    "backend/competition_templates/pbe_2d_v1/INCAR.dos",
    "backend/competition_templates/pbe_2d_v1/INCAR.relax",
    "backend/competition_templates/pbe_2d_v1/INCAR.scf",
    "backend/competition_templates/pbe_2d_v1/template.json",
    "backend/routers/competition_workflows.py",
    "backend/schemas.py",
    "backend/schemas_workflow.py",
    "backend/services/competition_attempt_inputs.py",
    "backend/services/competition_coordinator.py",
    "backend/services/competition_inputs.py",
    "backend/services/competition_reconcile.py",
    "backend/services/competition_vasp.py",
    "backend/services/competition_workflows.py",
    "backend/tests/test_107cup_authz.py",
    "backend/tests/test_107cup_deploy_contract.py",
    "backend/tests/test_107cup_service_recovery.py",
    "backend/tests/test_107cup_stage10_delivery_contract.py",
    "backend/tests/test_competition_attempt_inputs.py",
    "backend/tests/test_competition_coordinator.py",
    "backend/tests/test_competition_inputs.py",
    "backend/tests/test_competition_vasp.py",
    "backend/tests/test_competition_workflow_routes.py",
    "deploy/107cup/build.slurm",
    "deploy/107cup/generate-slurm-job-ledger.py",
    "deploy/107cup/generate-stage10-manifest.py",
    "deploy/107cup/relay/nginx.conf.example",
    "deploy/107cup/service_recovery.py",
    "deploy/107cup/service.slurm",
    "deploy/107cup/slurm/generic-vaspkit-preflight.slurm",
    "deploy/107cup/slurm/stage8-acceptance.py",
    "deploy/107cup/slurm/stage8-acceptance.slurm",
    "deploy/107cup/slurm/vasp-stage.slurm",
    "deploy/107cup/submit-generic-vaspkit-preflight.sh",
    "deploy/107cup/slurm/stage10-acceptance.py",
    "deploy/107cup/slurm/stage10-acceptance.slurm",
    "deploy/107cup/submit-stage10-acceptance.sh",
    "deploy/107cup/verify-runtime.sh",
    "docs/107cup/data-and-provenance.md",
    "docs/107cup/compute-cluster-run-data.md",
    "docs/107cup/demo-script.md",
    "docs/107cup/deployment.md",
    "docs/107cup/final-acceptance.md",
    "docs/107cup/implementation-plan.md",
    "docs/107cup/artifacts/slurm-job-ledger.csv",
    "docs/107cup/service-recovery-runbook.md",
    "docs/107cup/stage3-service-recovery-evidence.md",
    "docs/107cup/stage7-vasp-evidence.md",
    "docs/107cup/stage8-results-evidence.md",
    "docs/107cup/stage9-recovery-security-evidence.md",
    "frontend/src/components/AppShell.jsx",
    "frontend/src/features/auth/ChangePasswordDialog.css",
    "frontend/src/features/auth/ChangePasswordDialog.jsx",
    "frontend/src/features/auth/changePassword.js",
    "frontend/src/features/competition/CompetitionDataContext.jsx",
    "frontend/src/features/competition/components/CompetitionState.jsx",
    "frontend/src/features/competition/components/competitionComponents.css",
    "frontend/src/features/competition/data/apiCompetitionDataProvider.js",
    "frontend/src/pages/Login.jsx",
    "frontend/src/pages/competition/CompetitionNewCalculation.jsx",
    "frontend/src/pages/competition/CompetitionWorkflowDetail.jsx",
    "frontend/src/styles.css",
    "frontend/tests/changePassword107Cup.test.mjs",
    "frontend/tests/competitionDataProvider.test.mjs",
    "frontend/tests/competitionPages107Cup.test.mjs",
    "frontend/tests/competitionRoles107Cup.test.mjs",
)


def _canonical_text(path: Path) -> bytes:
    content = path.read_bytes()
    if b"\x00" in content:
        raise RuntimeError(f"manifest source is not UTF-8 text: {path}")
    text = content.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _digest(path: Path) -> str:
    return hashlib.sha256(_canonical_text(path)).hexdigest()


def generate(root: Path, output: Path) -> None:
    root = root.resolve(strict=True)
    entries = []
    for relative in sorted(STAGE10_MANIFEST_PATHS):
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise RuntimeError(f"unsafe manifest path: {relative}")
        path = root / Path(*pure.parts)
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"manifest source is missing or unsafe: {relative}")
        if path.resolve(strict=True).parent != path.parent.resolve(strict=True):
            raise RuntimeError(f"manifest source escapes through a symlink: {relative}")
        entries.append(f"{_digest(path)}  {relative}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
            handle.write("\n".join(entries) + "\n")
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    default_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument(
        "--output",
        type=Path,
        default=default_root / "docs" / "107cup" / "artifacts" / "manifest.sha256",
    )
    args = parser.parse_args()
    generate(args.root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
