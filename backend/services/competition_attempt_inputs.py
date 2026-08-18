from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, BinaryIO, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from models_workflow import WorkflowAttempt, WorkflowFile, WorkflowRun, WorkflowStep
from services.competition_vasp import FIXED_STAGE_ORDER, VaspPolicyError


ATTEMPT_PREPARING: Final = "preparing"
ATTEMPT_AWAITING_ACCEPTANCE: Final = "awaiting_acceptance"
ATTEMPT_SCIENTIFIC_FAILED: Final = "scientific_failed"
STEP_BLOCKED: Final = "blocked"

_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_MAX_METADATA_BYTES: Final = 8192
_HASH_CHUNK_BYTES: Final = 64 * 1024
_MAX_STANDARD_INPUT_BYTES: Final = 8 * 1024 * 1024
_MAX_CHGCAR_BYTES: Final = 512 * 1024 * 1024
_JOURNAL_VERSION: Final = 1
_O_BINARY: Final = getattr(os, "O_BINARY", 0)
_O_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_O_NONBLOCK: Final = getattr(os, "O_NONBLOCK", 0)
_O_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class PreparedFile:
    id: str
    relative_path: str
    sha256: str
    size_bytes: int
    source_file_id: str


@dataclass(frozen=True)
class PreparedAttempt:
    """Internal-only result; callers must not serialize ``directory`` to an API response."""

    attempt_id: str
    directory: Path
    names: frozenset[str]
    file_rows: tuple[PreparedFile, ...]


@dataclass(frozen=True)
class _InputSource:
    destination_name: str
    input_role: str
    row: WorkflowFile
    source_attempt_id: str | None


def _same_file_identity(expected: os.stat_result, opened: os.stat_result) -> bool:
    return bool(
        expected.st_ino
        and opened.st_ino
        and expected.st_dev == opened.st_dev
        and expected.st_ino == opened.st_ino
    )


def _close_descriptor(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _close_handle(handle: BinaryIO) -> None:
    try:
        handle.close()
    except OSError:
        pass
_STAGE5_INPUT_NAMES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType({
    "relax": ("INCAR", "KPOINTS", "POSCAR", "POTCAR.spec"),
    "scf": ("INCAR", "KPOINTS", "POTCAR.spec"),
    "band": ("INCAR", "KPOINTS", "POTCAR.spec"),
    "dos": ("INCAR", "KPOINTS", "POTCAR.spec"),
})
_PARENT_INPUTS: Final[Mapping[str, tuple[tuple[str, str, str], ...]]] = MappingProxyType({
    "relax": (),
    "scf": (("relax", "CONTCAR", "POSCAR"),),
    "band": (("scf", "POSCAR", "POSCAR"), ("scf", "CHGCAR", "CHGCAR")),
    "dos": (("scf", "POSCAR", "POSCAR"), ("scf", "CHGCAR", "CHGCAR")),
})


def prepare_attempt_inputs(
    session: Session,
    workflow_root: str | os.PathLike[str],
    *,
    owner_id: int,
    workflow_id: str,
    step_key: str,
    attempt_id: str,
    template_version: str,
    release_commit: str,
) -> PreparedAttempt:
    """Publish fixed VASP inputs and their ledger rows as one recoverable operation.

    This service owns the session commit/rollback boundary.  Callers must not wrap
    it in an outer transaction expecting atomicity across this filesystem publish.
    A private recovery journal bridges the unavoidable SQLite/filesystem boundary.
    """
    root = _workflow_root(workflow_root)
    workflow_id = _canonical_uuid("workflow_id", workflow_id)
    attempt_id = _canonical_uuid("attempt_id", attempt_id)
    if step_key not in FIXED_STAGE_ORDER:
        raise VaspPolicyError("stage_invalid", "attempt stage is not allowed")
    if not isinstance(template_version, str) or not template_version:
        raise VaspPolicyError("workflow_provenance_invalid", "workflow provenance is invalid")
    if not isinstance(release_commit, str) or re.fullmatch(r"[0-9a-f]{40}", release_commit) is None:
        raise VaspPolicyError("workflow_provenance_invalid", "workflow provenance is invalid")

    workflow, step, attempt = _owned_attempt(
        session, owner_id, workflow_id, step_key, attempt_id, template_version, release_commit
    )
    target = _attempt_target(root, workflow_id, attempt_id)
    journal = _recovery_journal_path(root, workflow_id, attempt_id)
    existing_rows = list(session.scalars(select(WorkflowFile).where(WorkflowFile.attempt_id == attempt_id)))

    if target.exists() or existing_rows:
        return _recover_or_return_published(
            session=session,
            root=root,
            workflow=workflow,
            step=step,
            attempt=attempt,
            target=target,
            journal=journal,
            existing_rows=existing_rows,
            template_version=template_version,
            release_commit=release_commit,
        )

    _clear_journal_proven_orphan_staging(root, workflow, step, attempt, journal)
    sources = _select_input_sources(session, root, workflow, step, attempt)
    row_payloads = _row_payloads(
        workflow=workflow,
        attempt=attempt,
        step_key=step.step_key,
        sources=sources,
        template_version=template_version,
        release_commit=release_commit,
    )
    staging = _new_staging_directory(root, workflow_id, attempt_id)
    journal_payload = _journal_payload(
        workflow_id=workflow_id,
        attempt_id=attempt_id,
        step_key=step_key,
        template_version=template_version,
        release_commit=release_commit,
        staging=staging,
        root=root,
        rows=row_payloads,
    )
    _write_recovery_journal(journal, journal_payload)

    published = False
    try:
        _make_private_directory(staging)
        for source, row_payload in zip(sources, row_payloads, strict=True):
            destination = staging / source.destination_name
            copy_verified_input(
                source=_safe_row_path(root, source.row.relative_path),
                destination=destination,
                expected_sha256=source.row.sha256,
                expected_size_bytes=source.row.size_bytes,
                source_file_id=source.row.id,
            )
        _verify_staged_rows(staging, row_payloads)
        session.add_all([_workflow_file_from_payload(row) for row in row_payloads])
        session.flush()
        _publish_staging_directory(staging, target)
        published = True
        try:
            _commit_prepared_rows(session)
        except Exception:
            session.rollback()
            # Target and journal are deliberately retained for restart recovery.
            raise VaspPolicyError(
                "input_ledger_recovery_required",
                "attempt input ledger recovery is required",
            ) from None
    except VaspPolicyError:
        if not published:
            session.rollback()
            _remove_owned_unpublished(root, workflow, step, attempt, staging, journal)
        raise
    except Exception:
        session.rollback()
        if not published:
            _remove_owned_unpublished(root, workflow, step, attempt, staging, journal)
        raise

    _remove_recovery_journal(journal)
    return _prepared_result(attempt_id, target, row_payloads)


def _workflow_root(value: str | os.PathLike[str]) -> Path:
    root = Path(value).resolve(strict=False)
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise VaspPolicyError("workflow_root_invalid", "workflow root is invalid")
    _make_private_directory(root)
    return root


def _canonical_uuid(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise VaspPolicyError("attempt_identity_invalid", "attempt identity is invalid")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise VaspPolicyError("attempt_identity_invalid", "attempt identity is invalid") from None
    if str(parsed) != value:
        raise VaspPolicyError("attempt_identity_invalid", "attempt identity is invalid")
    return value


def _owned_attempt(
    session: Session,
    owner_id: int,
    workflow_id: str,
    step_key: str,
    attempt_id: str,
    template_version: str,
    release_commit: str,
) -> tuple[WorkflowRun, WorkflowStep, WorkflowAttempt]:
    workflow = session.get(WorkflowRun, workflow_id)
    if workflow is None or workflow.owner_id != owner_id:
        raise VaspPolicyError("attempt_scope_invalid", "attempt scope is unavailable")
    if workflow.template_version != template_version or workflow.release_commit != release_commit:
        raise VaspPolicyError("workflow_provenance_invalid", "workflow provenance is invalid")
    step = session.scalar(
        select(WorkflowStep).where(
            WorkflowStep.workflow_id == workflow_id,
            WorkflowStep.step_key == step_key,
        )
    )
    attempt = session.get(WorkflowAttempt, attempt_id)
    if step is None or attempt is None or attempt.step_id != step.id:
        raise VaspPolicyError("attempt_scope_invalid", "attempt scope is unavailable")
    if attempt.status != ATTEMPT_PREPARING:
        raise VaspPolicyError("attempt_not_preparing", "attempt is not preparing inputs")
    return workflow, step, attempt


def _make_private_directory(path: Path) -> None:
    if path.exists():
        identity = path.lstat()
        if path.is_symlink() or not stat.S_ISDIR(identity.st_mode):
            raise VaspPolicyError("input_path_invalid", "attempt input path is invalid")
    else:
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    path.chmod(0o700)


def _attempt_target(root: Path, workflow_id: str, attempt_id: str) -> Path:
    workflow_directory = root / workflow_id
    attempts_directory = workflow_directory / "attempts"
    for directory in (workflow_directory, attempts_directory):
        if directory.exists():
            if directory.is_symlink() or not directory.is_dir():
                raise VaspPolicyError("input_path_invalid", "attempt input path is invalid")
        else:
            _make_private_directory(directory)
    return attempts_directory / attempt_id


def _recovery_journal_path(root: Path, workflow_id: str, attempt_id: str) -> Path:
    directory = root / ".attempt-recovery" / workflow_id
    _make_private_directory(root / ".attempt-recovery")
    _make_private_directory(directory)
    return directory / f"{attempt_id}.json"


def _new_staging_directory(root: Path, workflow_id: str, attempt_id: str) -> Path:
    directory = root / ".attempt-staging" / workflow_id
    _make_private_directory(root / ".attempt-staging")
    _make_private_directory(directory)
    return directory / f"{attempt_id}-{uuid.uuid4()}.staging"


def _safe_row_path(root: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise VaspPolicyError("input_path_invalid", "workflow file path is invalid")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        raise VaspPolicyError("input_path_invalid", "workflow file path is invalid")
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise VaspPolicyError("input_path_invalid", "workflow file path is invalid")
    return root.joinpath(*pure.parts)


def _metadata_object(value: object, *, code: str) -> dict[str, Any]:
    try:
        parsed = value if isinstance(value, dict) else json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise VaspPolicyError(code, "workflow file lineage is invalid") from None
    if not isinstance(parsed, dict):
        raise VaspPolicyError(code, "workflow file lineage is invalid")
    return parsed


def _select_input_sources(
    session: Session,
    root: Path,
    workflow: WorkflowRun,
    step: WorkflowStep,
    attempt: WorkflowAttempt,
) -> tuple[_InputSource, ...]:
    generated = list(session.scalars(select(WorkflowFile).where(
        WorkflowFile.workflow_id == workflow.id,
        WorkflowFile.source_kind == "generated",
    )))
    sources: list[_InputSource] = []
    for filename in _STAGE5_INPUT_NAMES[step.step_key]:
        matches = []
        for row in generated:
            metadata = _metadata_object(row.metadata_json, code="stage5_inputs_invalid")
            if metadata.get("step_key") == step.step_key and metadata.get("logical_path") == f"{step.step_key}/{filename}":
                matches.append(row)
        if len(matches) != 1:
            raise VaspPolicyError("stage5_inputs_invalid", "fixed Stage 5 inputs are invalid")
        row = matches[0]
        if (
            row.workflow_id != workflow.id
            or row.owner_id != workflow.owner_id
            or row.attempt_id is not None
            or row.source_kind != "generated"
        ):
            raise VaspPolicyError("stage5_inputs_invalid", "fixed Stage 5 inputs are invalid")
        _verify_source_row(root, row)
        sources.append(_InputSource(filename, f"stage5_{filename.lower()}", row, None))

    parent_rows = {
        parent_step_key: _accepted_parent_rows(
            session,
            root,
            workflow,
            parent_step_key,
            tuple(source_name for key, source_name, _ in _PARENT_INPUTS[step.step_key] if key == parent_step_key),
        )
        for parent_step_key in {key for key, _, _ in _PARENT_INPUTS[step.step_key]}
    }
    for parent_step_key, source_name, destination_name in _PARENT_INPUTS[step.step_key]:
        parent_attempt, rows = parent_rows[parent_step_key]
        row = rows[source_name]
        sources.append(_InputSource(
            destination_name,
            f"{parent_step_key}_{source_name.lower()}",
            row,
            parent_attempt.id,
        ))
    if len({source.destination_name for source in sources}) != len(sources):
        raise VaspPolicyError("input_destination_invalid", "attempt input destinations are invalid")
    return tuple(sources)


def _accepted_parent_rows(
    session: Session,
    root: Path,
    workflow: WorkflowRun,
    expected_step_key: str,
    expected_names: tuple[str, ...],
) -> tuple[WorkflowAttempt, dict[str, WorkflowFile]]:
    parents = list(session.execute(
        select(WorkflowAttempt, WorkflowStep)
        .join(WorkflowStep, WorkflowAttempt.step_id == WorkflowStep.id)
        .where(
            WorkflowStep.workflow_id == workflow.id,
            WorkflowStep.step_key == expected_step_key,
            WorkflowStep.status == "succeeded",
            WorkflowAttempt.status == "succeeded",
        )
    ))
    if not parents:
        raise VaspPolicyError("parent_not_accepted", "parent attempt is not accepted")
    if not expected_names or len(set(expected_names)) != len(expected_names):
        raise VaspPolicyError("parent_lineage_invalid", "parent attempt lineage is invalid")
    expected_set = set(expected_names)
    result: list[tuple[WorkflowAttempt, dict[str, WorkflowFile]]] = []
    for parent, _parent_step in parents:
        rows = list(session.scalars(select(WorkflowFile).where(
            WorkflowFile.workflow_id == workflow.id,
            WorkflowFile.attempt_id == parent.id,
            WorkflowFile.source_kind == "attempt_output",
        )))
        matching_rows: dict[str, list[WorkflowFile]] = {}
        for row in rows:
            if row.owner_id != workflow.owner_id:
                raise VaspPolicyError("parent_lineage_invalid", "parent attempt lineage is invalid")
            metadata = _metadata_object(row.metadata_json, code="parent_lineage_invalid")
            logical_path = metadata.get("logical_path")
            if logical_path not in expected_set:
                continue
            if metadata.get("step_key") != expected_step_key or metadata.get("accepted") is not True:
                raise VaspPolicyError("parent_lineage_invalid", "parent attempt lineage is invalid")
            _verify_source_row(root, row)
            matching_rows.setdefault(logical_path, []).append(row)
        if all(len(matching_rows.get(name, ())) == 1 for name in expected_names):
            result.append((parent, {name: matching_rows[name][0] for name in expected_names}))
    if len(result) != 1:
        raise VaspPolicyError("parent_lineage_invalid", "parent attempt lineage is invalid")
    return result[0]


def _verify_source_row(root: Path, row: WorkflowFile) -> None:
    if not isinstance(row.sha256, str) or _SHA256_RE.fullmatch(row.sha256) is None:
        raise VaspPolicyError("input_source_integrity", "attempt input integrity check failed")
    if not isinstance(row.size_bytes, int) or isinstance(row.size_bytes, bool) or row.size_bytes < 0:
        raise VaspPolicyError("input_source_integrity", "attempt input integrity check failed")
    _read_regular_file(
        _safe_row_path(root, row.relative_path),
        expected_sha256=row.sha256,
        expected_size_bytes=row.size_bytes,
    )


def read_regular_file(source: Path, *, expected_sha256: str) -> bytes:
    """Read one bounded regular evidence file with descriptor identity checks."""
    return _read_regular_file(source, expected_sha256=expected_sha256, expected_size_bytes=None)


def _read_regular_file(
    source: Path,
    *,
    expected_sha256: str,
    expected_size_bytes: int | None,
) -> bytes:
    content = bytearray()
    with _opened_verified_source(source, expected_sha256, expected_size_bytes) as (handle, size_bytes):
        maximum = _input_size_limit(source.name)
        if size_bytes > maximum:
            raise VaspPolicyError("input_source_too_large", "attempt input exceeds the policy limit")
        try:
            while chunk := handle.read(_HASH_CHUNK_BYTES):
                content.extend(chunk)
                if len(content) > maximum:
                    raise VaspPolicyError("input_source_too_large", "attempt input exceeds the policy limit")
        except VaspPolicyError:
            raise
        except OSError:
            raise VaspPolicyError("input_source_invalid", "attempt input is unavailable") from None
    actual = hashlib.sha256(content).hexdigest()
    if len(content) != size_bytes or actual != expected_sha256:
        raise VaspPolicyError("input_source_integrity", "attempt input integrity check failed")
    return bytes(content)


class _SourceHandle:
    def __init__(self, handle: BinaryIO, size_bytes: int):
        self.handle = handle
        self.size_bytes = size_bytes

    def __enter__(self):
        return self.handle, self.size_bytes

    def __exit__(self, _type, _value, _traceback):
        _close_handle(self.handle)


def _opened_verified_source(source: Path, expected_sha256: str, expected_size_bytes: int | None) -> _SourceHandle:
    try:
        before = source.lstat()
    except OSError:
        raise VaspPolicyError("input_source_invalid", "attempt input is unavailable") from None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise VaspPolicyError("input_source_invalid", "attempt input must be a regular file")
    flags = os.O_RDONLY | _O_BINARY | _O_CLOEXEC | _O_NONBLOCK | _O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(source, flags)
        opened = os.fstat(descriptor)
    except OSError:
        _close_descriptor(descriptor)
        raise VaspPolicyError("input_source_invalid", "attempt input is unavailable") from None
    if not stat.S_ISREG(opened.st_mode) or not _same_file_identity(before, opened):
        _close_descriptor(descriptor)
        raise VaspPolicyError("input_source_invalid", "attempt input changed while opening")
    if expected_size_bytes is not None and opened.st_size != expected_size_bytes:
        _close_descriptor(descriptor)
        raise VaspPolicyError("input_source_integrity", "attempt input integrity check failed")
    try:
        handle = os.fdopen(descriptor, "rb", closefd=True)
    except OSError:
        _close_descriptor(descriptor)
        raise VaspPolicyError("input_source_invalid", "attempt input is unavailable") from None
    return _SourceHandle(handle, opened.st_size)


def _input_size_limit(name: str) -> int:
    return _MAX_CHGCAR_BYTES if name == "CHGCAR" else _MAX_STANDARD_INPUT_BYTES


def copy_verified_input(
    *,
    source: Path,
    destination: Path,
    expected_sha256: str,
    source_file_id: str,
    expected_size_bytes: int | None = None,
) -> dict[str, object]:
    """Copy verified evidence privately without following or creating aliases."""
    maximum = _input_size_limit(destination.name)
    descriptor: int | None = None
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with _opened_verified_source(source, expected_sha256, expected_size_bytes) as (input_handle, source_size):
            if source_size > maximum:
                raise VaspPolicyError("input_source_too_large", "attempt input exceeds the policy limit")
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_CLOEXEC | _O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(descriptor, "wb", closefd=True) as output_handle:
                descriptor = None
                while chunk := input_handle.read(_HASH_CHUNK_BYTES):
                    size_bytes += len(chunk)
                    if size_bytes > maximum:
                        raise VaspPolicyError("input_source_too_large", "attempt input exceeds the policy limit")
                    output_handle.write(chunk)
                    digest.update(chunk)
                output_handle.flush()
                os.fsync(output_handle.fileno())
        actual = digest.hexdigest()
        if size_bytes != source_size or actual != expected_sha256:
            raise VaspPolicyError("input_copy_mismatch", "attempt input integrity check failed")
        identity = destination.lstat()
        if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1 or identity.st_size != size_bytes:
            raise VaspPolicyError("input_copy_mismatch", "attempt input integrity check failed")
        destination.chmod(0o600)
        return {
            "source_file_id": source_file_id,
            "source_sha256": expected_sha256,
            "sha256": actual,
            "size_bytes": size_bytes,
        }
    except FileExistsError:
        raise VaspPolicyError("input_destination_exists", "attempt input destination already exists") from None
    except VaspPolicyError:
        raise
    except OSError:
        raise VaspPolicyError("input_copy_failed", "attempt input could not be copied") from None
    finally:
        _close_descriptor(descriptor)


def _row_payloads(
    *,
    workflow: WorkflowRun,
    attempt: WorkflowAttempt,
    step_key: str,
    sources: tuple[_InputSource, ...],
    template_version: str,
    release_commit: str,
) -> tuple[dict[str, Any], ...]:
    rows = []
    for source in sources:
        rows.append({
            "id": str(uuid.uuid4()),
            "workflow_id": workflow.id,
            "attempt_id": attempt.id,
            "owner_id": workflow.owner_id,
            "relative_path": f"{workflow.id}/attempts/{attempt.id}/{source.destination_name}",
            "size_bytes": source.row.size_bytes,
            "sha256": source.row.sha256,
            "source_kind": "attempt_input",
            "metadata_json": {
                "logical_path": source.destination_name,
                "step_key": step_key,
                "input_role": source.input_role,
                "source_workflow_id": workflow.id,
                "source_attempt_id": source.source_attempt_id,
                "source_file_id": source.row.id,
                "source_sha256": source.row.sha256,
                "template_version": template_version,
                "release_commit": release_commit,
            },
        })
    return tuple(rows)


def _workflow_file_from_payload(payload: dict[str, Any]) -> WorkflowFile:
    return WorkflowFile(**payload)


def _journal_payload(
    *,
    workflow_id: str,
    attempt_id: str,
    step_key: str,
    template_version: str,
    release_commit: str,
    staging: Path,
    root: Path,
    rows: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    try:
        staging_relative = staging.relative_to(root).as_posix()
    except ValueError:
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is invalid") from None
    core = {
        "version": _JOURNAL_VERSION,
        "workflow_id": workflow_id,
        "attempt_id": attempt_id,
        "step_key": step_key,
        "template_version": template_version,
        "release_commit": release_commit,
        "staging_relative_path": staging_relative,
        "rows": list(rows),
    }
    encoded = _canonical_json_bytes(core)
    return {"payload": core, "sha256": hashlib.sha256(encoded).hexdigest()}


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError):
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is invalid") from None


def _write_recovery_journal(path: Path, journal: dict[str, Any]) -> None:
    content = _canonical_json_bytes(journal)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_CLOEXEC | _O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o600)
    except FileExistsError:
        raise VaspPolicyError("attempt_preparation_in_progress", "attempt preparation is already in progress") from None
    except OSError:
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is unavailable") from None
    finally:
        _close_descriptor(descriptor)


def _read_recovery_journal(path: Path) -> dict[str, Any]:
    try:
        identity = path.lstat()
        if stat.S_ISLNK(identity.st_mode) or not stat.S_ISREG(identity.st_mode) or identity.st_size > _MAX_METADATA_BYTES * 32:
            raise OSError
        content = path.read_bytes()
        journal = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is invalid") from None
    if not isinstance(journal, dict) or set(journal) != {"payload", "sha256"} or not isinstance(journal["payload"], dict):
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is invalid")
    if not isinstance(journal["sha256"], str) or hashlib.sha256(_canonical_json_bytes(journal["payload"])).hexdigest() != journal["sha256"]:
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is invalid")
    return journal["payload"]


def _remove_recovery_journal(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # A stale valid journal is harmless and is cleaned on the next retry.
        pass


def _remove_owned_unpublished(
    root: Path,
    workflow: WorkflowRun,
    step: WorkflowStep,
    attempt: WorkflowAttempt,
    staging: Path,
    journal: Path,
) -> None:
    if not journal.exists():
        return
    try:
        payload = _validate_journal_identity(_read_recovery_journal(journal), workflow, step, attempt)
        journal_staging = _safe_row_path(root, payload["staging_relative_path"])
        allowed_prefix = root / ".attempt-staging" / workflow.id
        if (
            journal_staging != staging
            or journal_staging.parent != allowed_prefix
            or not journal_staging.name.startswith(f"{attempt.id}-")
            or not journal_staging.name.endswith(".staging")
            or journal_staging.is_symlink()
        ):
            return
        if journal_staging.exists():
            if not journal_staging.is_dir():
                return
            shutil.rmtree(journal_staging)
        if journal_staging.exists() or journal_staging.is_symlink():
            return
    except (OSError, VaspPolicyError):
        return
    _remove_recovery_journal(journal)


def _clear_journal_proven_orphan_staging(
    root: Path,
    workflow: WorkflowRun,
    step: WorkflowStep,
    attempt: WorkflowAttempt,
    journal: Path,
) -> None:
    if not journal.exists():
        return
    payload = _validate_journal_identity(_read_recovery_journal(journal), workflow, step, attempt)
    staging = _safe_row_path(root, payload["staging_relative_path"])
    allowed_prefix = root / ".attempt-staging" / workflow.id
    if staging.parent != allowed_prefix or not staging.name.startswith(f"{attempt.id}-") or not staging.name.endswith(".staging"):
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is invalid")
    if staging.exists():
        if staging.is_symlink() or not staging.is_dir():
            raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is invalid")
        shutil.rmtree(staging)
    _remove_recovery_journal(journal)


def _publish_staging_directory(staging: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise VaspPolicyError("attempt_target_exists", "attempt directory already exists")
    try:
        os.replace(staging, target)
    except OSError:
        raise OSError("attempt input publish failed") from None


def _commit_prepared_rows(session: Session) -> None:
    session.commit()


def _verify_staged_rows(staging: Path, rows: tuple[dict[str, Any], ...]) -> None:
    expected_names = {Path(row["relative_path"]).name for row in rows}
    try:
        actual_names = {entry.name for entry in staging.iterdir()}
    except OSError:
        raise VaspPolicyError("input_copy_mismatch", "attempt input integrity check failed") from None
    if actual_names != expected_names:
        raise VaspPolicyError("input_copy_mismatch", "attempt input integrity check failed")
    for row in rows:
        path = staging / Path(row["relative_path"]).name
        _verify_file_payload(path, row)


def _verify_file_payload(path: Path, payload: dict[str, Any]) -> None:
    content = _read_regular_file(
        path,
        expected_sha256=payload["sha256"],
        expected_size_bytes=payload["size_bytes"],
    )
    if len(content) != payload["size_bytes"]:
        raise VaspPolicyError("input_copy_mismatch", "attempt input integrity check failed")


def _prepared_result(attempt_id: str, target: Path, rows: Sequence[dict[str, Any]]) -> PreparedAttempt:
    prepared = tuple(PreparedFile(
        id=row["id"], relative_path=row["relative_path"], sha256=row["sha256"],
        size_bytes=row["size_bytes"], source_file_id=row["metadata_json"]["source_file_id"],
    ) for row in rows)
    return PreparedAttempt(attempt_id, target, frozenset(Path(row["relative_path"]).name for row in rows), prepared)


def _recover_or_return_published(
    *,
    session: Session,
    root: Path,
    workflow: WorkflowRun,
    step: WorkflowStep,
    attempt: WorkflowAttempt,
    target: Path,
    journal: Path,
    existing_rows: list[WorkflowFile],
    template_version: str,
    release_commit: str,
) -> PreparedAttempt:
    if not target.exists() or target.is_symlink() or not target.is_dir():
        raise VaspPolicyError("input_publication_mismatch", "attempt publication is incomplete")
    if existing_rows:
        rows = tuple(_payload_from_existing(row, workflow, attempt, template_version, release_commit) for row in existing_rows)
        expected_sources = _select_input_sources(session, root, workflow, step, attempt)
        expected_rows = _row_payloads(
            workflow=workflow, attempt=attempt, step_key=step.step_key, sources=expected_sources,
            template_version=template_version, release_commit=release_commit,
        )
        if not _same_recovery_rows(rows, expected_rows):
            raise VaspPolicyError("input_publication_mismatch", "attempt publication does not match current lineage")
        _validate_published_rows(target, rows, step.step_key)
        if journal.exists():
            payload = _validate_journal_identity(_read_recovery_journal(journal), workflow, step, attempt)
            if tuple(payload.get("rows", ())) != rows:
                raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is invalid")
            _remove_recovery_journal(journal)
        return _prepared_result(attempt.id, target, rows)
    if not journal.exists():
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is unavailable")
    payload = _validate_journal_identity(_read_recovery_journal(journal), workflow, step, attempt)
    rows_value = payload.get("rows")
    if not isinstance(rows_value, list):
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is invalid")
    rows = tuple(rows_value)
    expected_sources = _select_input_sources(session, root, workflow, step, attempt)
    expected_rows = _row_payloads(
        workflow=workflow, attempt=attempt, step_key=step.step_key, sources=expected_sources,
        template_version=template_version, release_commit=release_commit,
    )
    # IDs are journal-originated; all other immutable provenance must still match.
    if not _same_recovery_rows(rows, expected_rows):
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal does not match current lineage")
    _validate_published_rows(target, rows, step.step_key)
    try:
        session.add_all([_workflow_file_from_payload(row) for row in rows])
        _commit_prepared_rows(session)
    except Exception:
        session.rollback()
        raise VaspPolicyError("input_ledger_recovery_required", "attempt input ledger recovery is required") from None
    _remove_recovery_journal(journal)
    return _prepared_result(attempt.id, target, rows)


def _validate_journal_identity(
    payload: dict[str, Any],
    workflow: WorkflowRun,
    step: WorkflowStep,
    attempt: WorkflowAttempt,
) -> dict[str, Any]:
    required = {"version", "workflow_id", "attempt_id", "step_key", "template_version", "release_commit", "staging_relative_path", "rows"}
    if (
        set(payload) != required
        or payload.get("version") != _JOURNAL_VERSION
        or payload.get("workflow_id") != workflow.id
        or payload.get("attempt_id") != attempt.id
        or payload.get("step_key") != step.step_key
        or payload.get("template_version") != workflow.template_version
        or payload.get("release_commit") != workflow.release_commit
    ):
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is invalid")
    if not isinstance(payload.get("staging_relative_path"), str):
        raise VaspPolicyError("input_recovery_invalid", "attempt recovery journal is invalid")
    return payload


def _payload_from_existing(
    row: WorkflowFile,
    workflow: WorkflowRun,
    attempt: WorkflowAttempt,
    template_version: str,
    release_commit: str,
) -> dict[str, Any]:
    if row.workflow_id != workflow.id or row.attempt_id != attempt.id or row.owner_id != workflow.owner_id or row.source_kind != "attempt_input":
        raise VaspPolicyError("input_publication_mismatch", "attempt input ledger is invalid")
    metadata = _metadata_object(row.metadata_json, code="input_publication_mismatch")
    required = {"logical_path", "step_key", "input_role", "source_workflow_id", "source_attempt_id", "source_file_id", "source_sha256", "template_version", "release_commit"}
    if set(metadata) != required or metadata["source_workflow_id"] != workflow.id or metadata["template_version"] != template_version or metadata["release_commit"] != release_commit:
        raise VaspPolicyError("input_publication_mismatch", "attempt input ledger is invalid")
    return {"id": row.id, "workflow_id": row.workflow_id, "attempt_id": row.attempt_id, "owner_id": row.owner_id, "relative_path": row.relative_path, "size_bytes": row.size_bytes, "sha256": row.sha256, "source_kind": row.source_kind, "metadata_json": metadata}


def _same_recovery_rows(actual: tuple[dict[str, Any], ...], expected: tuple[dict[str, Any], ...]) -> bool:
    if len(actual) != len(expected):
        return False
    for saved, current in zip(sorted(actual, key=lambda row: row.get("relative_path", "")), sorted(expected, key=lambda row: row["relative_path"])):
        if not isinstance(saved, dict) or {key: value for key, value in saved.items() if key != "id"} != {key: value for key, value in current.items() if key != "id"}:
            return False
    return True


def _validate_published_rows(target: Path, rows: tuple[dict[str, Any], ...], step_key: str) -> None:
    expected_names = _expected_destination_names(step_key)
    if len(rows) != len(expected_names) or {Path(row.get("relative_path", "")).name for row in rows} != expected_names:
        raise VaspPolicyError("input_publication_mismatch", "attempt input ledger is incomplete")
    expected_prefix = f"{rows[0]['workflow_id']}/attempts/{rows[0]['attempt_id']}/" if rows else ""
    if any(
        not isinstance(row.get("relative_path"), str)
        or row["relative_path"] != expected_prefix + Path(row["relative_path"]).name
        for row in rows
    ):
        raise VaspPolicyError("input_publication_mismatch", "attempt input ledger is invalid")
    try:
        names = {entry.name for entry in target.iterdir()}
    except OSError:
        raise VaspPolicyError("input_publication_mismatch", "attempt publication is unavailable") from None
    if names != expected_names:
        raise VaspPolicyError("input_publication_mismatch", "attempt publication is invalid")
    for row in rows:
        _verify_file_payload(target / Path(row["relative_path"]).name, row)


def _expected_destination_names(step_key: str) -> set[str]:
    return set(_STAGE5_INPUT_NAMES[step_key]) | {destination for _parent, _source, destination in _PARENT_INPUTS[step_key]}
