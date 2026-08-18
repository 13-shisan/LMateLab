from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from competition_runtime import release_commit, workflow_root
from database import SessionLocal
from main_107cup import build_production_coordinator
from models import User
from models_workflow import WorkflowFile, WorkflowRun, canonical_json
from schemas_workflow import DraftCreateRequest
from services.competition_inputs import FIXED_STEPS
from services.competition_vasp import render_acceptance_scf_incar
from services.competition_workflows import (
    append_workflow_event,
    confirm_workflow,
    create_draft,
)


PROFILE = "scf_nonconvergence_v1"
_ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INPUT_NAMES = ("INCAR", "KPOINTS", "POSCAR", "POTCAR.spec")
_LOGICAL_PATHS = frozenset(
    f"{step}/{name}" for step in FIXED_STEPS for name in _INPUT_NAMES
)


def _metadata(value: str | dict[str, object]) -> dict[str, object]:
    decoded = value if isinstance(value, dict) else json.loads(value)
    if not isinstance(decoded, dict):
        raise RuntimeError("workflow metadata is invalid")
    return json.loads(canonical_json(decoded))


def _checked_generated_file(
    root: Path,
    row: WorkflowFile,
    *,
    owner_id: int,
    workflow_id: str,
) -> tuple[str, Path, bytes]:
    metadata = _metadata(row.metadata_json)
    logical_path = metadata.get("logical_path")
    if (
        row.workflow_id != workflow_id
        or row.owner_id != owner_id
        or row.attempt_id is not None
        or row.source_kind != "generated"
        or logical_path not in _LOGICAL_PATHS
        or metadata.get("step_key") != str(logical_path).split("/", 1)[0]
        or not isinstance(row.sha256, str)
        or _SHA256_RE.fullmatch(row.sha256) is None
    ):
        raise RuntimeError("workflow input ledger is invalid")
    relative = PurePosixPath(row.relative_path)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        raise RuntimeError("workflow input path is invalid")
    path = root.joinpath(*relative.parts)
    try:
        path.resolve(strict=True).relative_to(root)
        identity = path.lstat()
        content = path.read_bytes()
    except (OSError, ValueError):
        raise RuntimeError("workflow input file is unavailable") from None
    if (
        path.is_symlink()
        or not stat.S_ISREG(identity.st_mode)
        or len(content) != row.size_bytes
        or hashlib.sha256(content).hexdigest() != row.sha256
    ):
        raise RuntimeError("workflow input integrity check failed")
    return str(logical_path), path, content


def _manifest_entry(row: WorkflowFile) -> dict[str, object]:
    metadata = _metadata(row.metadata_json)
    return {
        "logical_path": metadata["logical_path"],
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "source_kind": row.source_kind,
    }


def _manifest_hash(entries: list[dict[str, object]]) -> str:
    ordered = sorted(entries, key=lambda item: str(item["logical_path"]))
    return hashlib.sha256(canonical_json(ordered).encode("utf-8")).hexdigest()


def _replace_private(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.profile-{uuid.uuid4()}")
    descriptor: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def apply_internal_profile(
    session: Session,
    root: Path,
    *,
    owner_id: int,
    workflow_id: str,
    profile: str,
) -> str:
    if profile != PROFILE:
        raise RuntimeError("acceptance profile is invalid")
    root = root.resolve(strict=True)
    run = session.get(WorkflowRun, workflow_id)
    if run is None or run.owner_id != owner_id or run.status != "draft":
        raise RuntimeError("acceptance workflow is unavailable")

    rows = list(
        session.scalars(
            select(WorkflowFile).where(
                WorkflowFile.workflow_id == workflow_id,
                WorkflowFile.source_kind == "generated",
            )
        )
    )
    checked = [
        (row, *_checked_generated_file(root, row, owner_id=owner_id, workflow_id=workflow_id))
        for row in rows
    ]
    if len(checked) != len(_LOGICAL_PATHS) or {item[1] for item in checked} != _LOGICAL_PATHS:
        raise RuntimeError("acceptance workflow inputs are invalid")

    metadata = _metadata(run.metadata_json)
    manifest = sorted(
        (_manifest_entry(row) for row in rows),
        key=lambda item: str(item["logical_path"]),
    )
    if metadata.get("input_manifest") != manifest or run.input_sha256 != _manifest_hash(manifest):
        raise RuntimeError("acceptance workflow manifest is invalid")

    target_row, logical_path, target_path, original = next(
        item for item in checked if item[1] == "scf/INCAR"
    )
    if logical_path == "scf/INCAR":
        rendered = render_acceptance_scf_incar(original)
    rendered_sha256 = hashlib.sha256(rendered).hexdigest()
    if rendered == original:
        raise RuntimeError("acceptance profile did not change SCF input")

    replaced = False
    try:
        _replace_private(target_path, rendered)
        replaced = True
        target_row.sha256 = rendered_sha256
        target_row.size_bytes = len(rendered)
        updated_manifest = sorted(
            (_manifest_entry(row) for row in rows),
            key=lambda item: str(item["logical_path"]),
        )
        metadata["input_manifest"] = updated_manifest
        metadata["acceptance_profile"] = PROFILE
        run.metadata_json = metadata
        run.input_sha256 = _manifest_hash(updated_manifest)
        append_workflow_event(
            session,
            workflow_id=workflow_id,
            event_type="acceptance_profile_configured",
            payload={
                "profile": "scf_nonconvergence_v1",
                "scf_incar_sha256": rendered_sha256,
                "input_sha256": run.input_sha256,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        if replaced:
            _replace_private(target_path, original)
        raise
    return run.input_sha256


def _operator_id(session: Session, alias: str) -> int:
    if _ALIAS_RE.fullmatch(alias) is None:
        raise RuntimeError("operator alias is invalid")
    operators = list(
        session.scalars(
            select(User)
            .where(User.alias == alias, User.role == "operator")
            .limit(2)
        )
    )
    if len(operators) != 1:
        raise RuntimeError("operator identity is unavailable")
    return int(operators[0].id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("scf_nonconvergence_v1",), required=True)
    parser.add_argument("--operator-alias", default="pb23030683")
    args = parser.parse_args()

    root = workflow_root()
    payload = DraftCreateRequest.model_validate(
        {
            "template_version": "mos2_v1",
            "source_kind": "builtin",
            "steps": list(FIXED_STEPS),
            "parameters": {},
        }
    )
    with SessionLocal() as session:
        owner_id = _operator_id(session, args.operator_alias)
        draft = create_draft(
            session,
            root,
            owner_id=owner_id,
            payload=payload,
            release_commit=release_commit(),
        )
        apply_internal_profile(
            session,
            root,
            owner_id=owner_id,
            workflow_id=draft.id,
            profile=args.profile,
        )
        confirm_workflow(
            session,
            root,
            owner_id=owner_id,
            workflow_id=draft.id,
        )

    coordinator = build_production_coordinator()
    outcome = coordinator.start(draft.id, owner_id)
    print(outcome.workflow_id, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
