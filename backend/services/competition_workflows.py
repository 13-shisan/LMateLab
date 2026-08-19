from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from models_workflow import (
    WorkflowAttempt,
    WorkflowEvent,
    WorkflowFile,
    WorkflowRun,
    WorkflowStep,
    WorkflowTemplate,
    canonical_json,
)
from schemas_workflow import (
    DraftCreateRequest,
    StructureUploadResult,
    WorkflowMutationResult,
)
from services.competition_inputs import (
    FIXED_STEPS,
    InputValidationError,
    load_template,
    materialize_inputs,
    parse_structure_bytes,
    validate_draft_payload,
)
from services.competition_vasp import render_acceptance_scf_incar


_INTERNAL_ACCEPTANCE_PROFILE = "scf_nonconvergence_v1"


class WorkflowServiceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _root_path(workflow_root: str | os.PathLike[str]) -> Path:
    root = Path(workflow_root).resolve()
    if root.exists() and not root.is_dir():
        raise InputValidationError("workflow root is not a directory")
    return root


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def _safe_relative_path(root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise WorkflowServiceError("invalid_file", "workflow file path is invalid")
    if "\\" in relative_path:
        raise WorkflowServiceError("invalid_file", "workflow file path is invalid")
    parts = PurePosixPath(relative_path).parts
    if not parts or PurePosixPath(relative_path).is_absolute() or any(
        part in ("", ".", "..") for part in parts
    ):
        raise WorkflowServiceError("invalid_file", "workflow file path is invalid")
    path = root.joinpath(*parts)
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise WorkflowServiceError("invalid_file", "workflow file path is invalid") from exc
    current = root
    for part in parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise WorkflowServiceError("invalid_file", "workflow file is not regular")
    return path


def _read_verified_file(root: Path, row: WorkflowFile) -> bytes:
    path = _safe_relative_path(root, row.relative_path)
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise WorkflowServiceError("invalid_file", "workflow file is unavailable") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise WorkflowServiceError("invalid_file", "workflow file is not regular")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise WorkflowServiceError("invalid_file", "workflow file is unavailable") from exc
    if len(content) != row.size_bytes or hashlib.sha256(content).hexdigest() != row.sha256:
        raise WorkflowServiceError("invalid_file", "workflow file integrity check failed")
    return content


def _metadata(value: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        try:
            decoded = json.loads(canonical_json(value))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WorkflowServiceError("invalid_metadata", "workflow metadata is invalid") from exc
        return decoded
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise WorkflowServiceError("invalid_metadata", "workflow metadata is invalid") from exc
    if not isinstance(decoded, dict):
        raise WorkflowServiceError("invalid_metadata", "workflow metadata is invalid")
    return decoded


def _manifest_entry(row: WorkflowFile) -> dict[str, Any]:
    metadata = _metadata(row.metadata_json)
    logical_path = metadata.get("logical_path")
    if not isinstance(logical_path, str) or not logical_path:
        raise WorkflowServiceError("invalid_manifest", "workflow input manifest is invalid")
    return {
        "logical_path": logical_path,
        "sha256": row.sha256,
        "size_bytes": row.size_bytes,
        "source_kind": row.source_kind,
    }


def _manifest_hash(entries: list[dict[str, Any]]) -> str:
    encoded = canonical_json(sorted(entries, key=lambda item: item["logical_path"]))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _result(run: WorkflowRun) -> WorkflowMutationResult:
    metadata = _metadata(run.metadata_json)
    return WorkflowMutationResult(
        id=run.id,
        status=run.status,
        input_sha256=run.input_sha256 or "",
        template_version=run.template_version,
        source_kind=run.source_kind,
        structure_summary=metadata.get("structure_summary", {}),
    )


def stage_structure(
    session: Session,
    workflow_root: str | os.PathLike[str],
    *,
    owner_id: int,
    content: bytes,
    filename: str,
) -> StructureUploadResult:
    parsed = parse_structure_bytes(content, filename)
    root = _root_path(workflow_root)
    upload_id = str(uuid.uuid4())
    relative_path = f"incoming/{owner_id}/{upload_id}"
    final_path = _safe_relative_path(root, relative_path)
    temporary_path = final_path.with_name(f".{upload_id}.tmp")
    digest = hashlib.sha256(content).hexdigest()
    metadata = {
        "consumed": False,
        "original_filename": parsed.original_filename,
        "source_format": parsed.source_format,
        "structure_summary": parsed.summary,
    }

    completed = False
    try:
        _ensure_private_directory(root)
        _ensure_private_directory(root / "incoming")
        _ensure_private_directory(final_path.parent)
        with temporary_path.open("xb") as handle:
            handle.write(content)
        temporary_path.chmod(0o600)
        temporary_path.replace(final_path)
        completed = True
        session.add(
            WorkflowFile(
                id=upload_id,
                owner_id=owner_id,
                relative_path=relative_path,
                size_bytes=len(content),
                sha256=digest,
                source_kind="upload",
                metadata_json=metadata,
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        for path in (temporary_path, final_path if completed else None):
            if path is not None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        raise

    return StructureUploadResult(
        id=upload_id,
        relative_path=relative_path,
        size_bytes=len(content),
        sha256=digest,
        source_format=parsed.source_format,
        summary=parsed.summary,
    )


def _request_payload(payload: DraftCreateRequest | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, DraftCreateRequest):
        request = payload.model_dump(mode="json", exclude_none=True)
    elif isinstance(payload, dict):
        request = DraftCreateRequest.model_validate(payload).model_dump(
            mode="json", exclude_none=True
        )
    else:
        raise InputValidationError("draft payload must be an object")
    return validate_draft_payload(request)


def _load_upload(
    session: Session,
    root: Path,
    owner_id: int,
    upload_id: str,
):
    row = session.scalar(
        select(WorkflowFile)
        .where(WorkflowFile.id == upload_id)
        .where(WorkflowFile.owner_id == owner_id)
        .where(WorkflowFile.workflow_id.is_(None))
        .where(WorkflowFile.attempt_id.is_(None))
        .where(WorkflowFile.source_kind == "upload")
    )
    if row is None:
        raise WorkflowServiceError("upload_unavailable", "structure upload is unavailable")
    metadata = _metadata(row.metadata_json)
    if metadata.get("consumed") is not False:
        raise WorkflowServiceError("upload_unavailable", "structure upload is unavailable")
    content = _read_verified_file(root, row)
    filename = metadata.get("original_filename")
    if not isinstance(filename, str):
        raise WorkflowServiceError("upload_unavailable", "structure upload is unavailable")
    try:
        parsed = parse_structure_bytes(content, filename)
    except InputValidationError as exc:
        raise WorkflowServiceError(
            "upload_unavailable", "structure upload is unavailable"
        ) from exc
    return row, metadata, parsed


def _claim_upload(
    session: Session,
    upload: WorkflowFile,
    workflow_id: str,
) -> bool:
    metadata = _metadata(upload.metadata_json)
    if metadata.get("consumed") is not False:
        return False
    metadata["consumed"] = True
    metadata["consumed_by_workflow_id"] = workflow_id
    result = session.execute(
        update(WorkflowFile)
        .where(
            WorkflowFile.id == upload.id,
            WorkflowFile.owner_id == upload.owner_id,
            WorkflowFile.workflow_id.is_(None),
            WorkflowFile.attempt_id.is_(None),
            WorkflowFile.source_kind == "upload",
        )
        .values(
            workflow_id=workflow_id,
            metadata_json=metadata,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _ambiguous_draft_commit() -> WorkflowServiceError:
    return WorkflowServiceError(
        "draft_commit_outcome_ambiguous",
        "workflow draft commit outcome is ambiguous; evidence was retained",
    )


def _resolve_draft_commit_outcome(
    bind,
    root: Path,
    *,
    workflow_id: str,
    owner_id: int,
    release_commit: str,
    input_sha256: str,
    directory_id: str,
    metadata: dict[str, Any],
    events: list[tuple[str, dict[str, Any]]],
) -> WorkflowMutationResult | None:
    try:
        with Session(bind=bind) as verification_session:
            run = verification_session.get(WorkflowRun, workflow_id)
            if run is None:
                return None
            _validate_workflow(verification_session, root, run)
            files = verification_session.scalars(
                select(WorkflowFile).where(WorkflowFile.workflow_id == run.id)
            ).all()
            persisted_events = verification_session.scalars(
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_id == run.id)
                .order_by(WorkflowEvent.sequence)
            ).all()
            if (
                run.owner_id != owner_id
                or run.status != "draft"
                or run.material != "MoS2"
                or run.source_kind != "builtin"
                or run.release_commit != release_commit
                or run.input_sha256 != input_sha256
                or _metadata(run.metadata_json) != metadata
                or any(
                    row.owner_id != owner_id
                    or row.attempt_id is not None
                    or row.source_kind != "generated"
                    or row.relative_path
                    != f'{directory_id}/{_metadata(row.metadata_json).get("logical_path")}'
                    for row in files
                )
                or [
                    (
                        event.sequence,
                        event.event_type,
                        _metadata(event.payload_json),
                    )
                    for event in persisted_events
                ]
                != [
                    (sequence, event_type, payload)
                    for sequence, (event_type, payload) in enumerate(events, start=1)
                ]
            ):
                raise _ambiguous_draft_commit()
            return _result(run)
    except WorkflowServiceError as exc:
        if exc.code == "draft_commit_outcome_ambiguous":
            raise
        raise _ambiguous_draft_commit() from exc
    except Exception as exc:
        raise _ambiguous_draft_commit() from exc


def create_draft(
    session: Session,
    workflow_root: str | os.PathLike[str],
    *,
    owner_id: int,
    payload: DraftCreateRequest | dict[str, Any],
    release_commit: str,
) -> WorkflowMutationResult:
    return _create_draft_common(
        session,
        workflow_root,
        owner_id=owner_id,
        payload=payload,
        release_commit=release_commit,
        acceptance_profile=None,
    )


def create_internal_acceptance_draft(
    session: Session,
    workflow_root: str | os.PathLike[str],
    *,
    owner_id: int,
    payload: DraftCreateRequest | dict[str, Any],
    release_commit: str,
    profile: str,
) -> WorkflowMutationResult:
    if profile != _INTERNAL_ACCEPTANCE_PROFILE:
        raise WorkflowServiceError(
            "invalid_acceptance_profile", "acceptance profile is invalid"
        )
    return _create_draft_common(
        session,
        workflow_root,
        owner_id=owner_id,
        payload=payload,
        release_commit=release_commit,
        acceptance_profile=profile,
    )


def _create_draft_common(
    session: Session,
    workflow_root: str | os.PathLike[str],
    *,
    owner_id: int,
    payload: DraftCreateRequest | dict[str, Any],
    release_commit: str,
    acceptance_profile: str | None,
) -> WorkflowMutationResult:
    if re.fullmatch(r"[0-9a-f]{40}", release_commit) is None:
        raise WorkflowServiceError(
            "invalid_release_commit", "workflow release commit is invalid"
        )
    validated = _request_payload(payload)
    if acceptance_profile is not None and (
        validated["source_kind"] != "builtin" or validated["parameters"]
    ):
        raise WorkflowServiceError(
            "invalid_acceptance_profile",
            "acceptance profile requires the fixed builtin payload",
        )
    root = _root_path(workflow_root)
    upload_id = validated.get("structure_upload_id")
    generated_directory: Path | None = None
    commit_started = False
    bind = session.get_bind()

    try:
        upload_row = None
        structure = None
        if upload_id:
            upload_row, _upload_metadata, structure = _load_upload(
                session, root, owner_id, upload_id
            )

        materialized = materialize_inputs(
            root,
            structure,
            validated,
            _scf_incar_transform=(
                render_acceptance_scf_incar
                if acceptance_profile is not None
                else None
            ),
        )
        generated_directory = Path(materialized["directory"])
        acceptance_scf_sha256 = None
        if acceptance_profile is not None:
            scf_records = [
                record
                for record in materialized["files"]
                if PurePosixPath(record["relative_path"]).parts[1:]
                == ("scf", "INCAR")
            ]
            if len(scf_records) != 1:
                raise WorkflowServiceError(
                    "invalid_acceptance_materialization",
                    "acceptance workflow input materialization is invalid",
                )
            acceptance_scf_sha256 = scf_records[0]["sha256"]
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            template_version=validated["template_version"],
            material="MoS2",
            source_kind=validated["source_kind"],
            status="draft",
            release_commit=release_commit,
        )
        session.add(run)
        session.flush()
        if upload_row is not None:
            if not _claim_upload(session, upload_row, run.id):
                raise WorkflowServiceError(
                    "upload_unavailable", "structure upload is unavailable"
                )
        template_definition = load_template(validated["template_version"])
        template_row = session.scalar(
            select(WorkflowTemplate).where(
                WorkflowTemplate.template_key == "mos2",
                WorkflowTemplate.version == validated["template_version"],
            )
        )
        if template_row is None:
            session.add(
                WorkflowTemplate(
                    template_key="mos2",
                    version=validated["template_version"],
                    definition_json=template_definition,
                )
            )

        dependencies = {
            definition["key"]: definition["depends_on"]
            for definition in template_definition["steps"]
        }
        for position, step_key in enumerate(FIXED_STEPS):
            parameters = {
                "depends_on": dependencies[step_key],
                "parameters": validated["parameters"].get(step_key, {}),
            }
            session.add(
                WorkflowStep(
                    workflow=run,
                    step_key=step_key,
                    position=position,
                    status="waiting",
                    parameters_json=parameters,
                )
            )

        generated_rows = []
        for record in materialized["files"]:
            relative_parts = PurePosixPath(record["relative_path"]).parts
            logical_path = "/".join(relative_parts[1:])
            row = WorkflowFile(
                workflow=run,
                owner_id=owner_id,
                relative_path=record["relative_path"],
                size_bytes=record["size_bytes"],
                sha256=record["sha256"],
                source_kind="generated",
                metadata_json={
                    "logical_path": logical_path,
                    "step_key": record["step_key"],
                },
            )
            generated_rows.append(row)
            session.add(row)

        manifest_entries = [_manifest_entry(row) for row in generated_rows]
        manifest_hash = _manifest_hash(manifest_entries)
        run.input_sha256 = manifest_hash
        run_metadata = {
            "input_manifest": sorted(
                manifest_entries, key=lambda item: item["logical_path"]
            ),
            "normalized_payload": {
                key: value
                for key, value in validated.items()
                if key != "canonical_json"
            },
            "structure_summary": materialized["structure_summary"],
        }
        if acceptance_profile is not None:
            run_metadata["acceptance_profile"] = acceptance_profile
        run.metadata_json = run_metadata
        draft_payload = {
            "input_sha256": manifest_hash,
            "source_kind": validated["source_kind"],
            "template_version": validated["template_version"],
            "release_commit": release_commit,
        }
        event_definitions = [("draft_created", draft_payload)]
        if acceptance_profile is not None:
            event_definitions.append(
                (
                    "acceptance_profile_configured",
                    {
                        "profile": acceptance_profile,
                        "scf_incar_sha256": acceptance_scf_sha256,
                        "input_sha256": manifest_hash,
                    },
                )
            )
        for sequence, (event_type, event_payload) in enumerate(
            event_definitions, start=1
        ):
            session.add(
                WorkflowEvent(
                    workflow=run,
                    sequence=sequence,
                    event_type=event_type,
                    payload_json=event_payload,
                )
            )

        commit_started = True
        session.commit()
    except Exception:
        session.rollback()
        if commit_started and acceptance_profile is not None:
            committed = _resolve_draft_commit_outcome(
                bind,
                root,
                workflow_id=run.id,
                owner_id=owner_id,
                release_commit=release_commit,
                input_sha256=manifest_hash,
                directory_id=generated_directory.name,
                metadata=run_metadata,
                events=event_definitions,
            )
            if committed is not None:
                return committed
        if generated_directory is not None:
            if acceptance_profile is None:
                shutil.rmtree(generated_directory, ignore_errors=True)
        raise
    return _result(run)


def _next_event_sequence(session: Session, workflow_id: str) -> int:
    current = session.scalar(
        select(func.max(WorkflowEvent.sequence)).where(
            WorkflowEvent.workflow_id == workflow_id
        )
    )
    return int(current or 0) + 1


def append_workflow_event(
    session: Session,
    *,
    workflow_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> WorkflowEvent:
    event = WorkflowEvent(
        workflow_id=workflow_id,
        sequence=_next_event_sequence(session, workflow_id),
        event_type=event_type,
        payload_json=payload,
    )
    session.add(event)
    return event


def _transition_workflow_status(
    session: Session,
    *,
    owner_id: int,
    workflow_id: str,
    expected_status: str,
    target_status: str,
    input_sha256: str,
) -> bool:
    result = session.execute(
        update(WorkflowRun)
        .where(
            WorkflowRun.id == workflow_id,
            WorkflowRun.owner_id == owner_id,
            WorkflowRun.status == expected_status,
            WorkflowRun.input_sha256 == input_sha256,
        )
        .values(
            status=target_status,
            updated_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _claim_workflow_validation(
    session: Session,
    *,
    owner_id: int,
    workflow_id: str,
    input_sha256: str,
) -> bool:
    return _transition_workflow_status(
        session,
        owner_id=owner_id,
        workflow_id=workflow_id,
        expected_status="draft",
        target_status="validating",
        input_sha256=input_sha256,
    )


def _reload_owned_workflow(
    session: Session,
    *,
    owner_id: int,
    workflow_id: str,
) -> WorkflowRun | None:
    return session.scalar(
        select(WorkflowRun)
        .where(
            WorkflowRun.id == workflow_id,
            WorkflowRun.owner_id == owner_id,
        )
        .execution_options(populate_existing=True)
    )


def _validate_workflow(session: Session, root: Path, run: WorkflowRun) -> None:
    template = load_template(run.template_version)
    template_row = session.scalar(
        select(WorkflowTemplate).where(
            WorkflowTemplate.template_key == "mos2",
            WorkflowTemplate.version == run.template_version,
        )
    )
    if template_row is None or _metadata(template_row.definition_json) != template:
        raise WorkflowServiceError("invalid_template", "workflow template is invalid")

    metadata = _metadata(run.metadata_json)
    normalized_payload = metadata.get("normalized_payload")
    if not isinstance(normalized_payload, dict):
        raise WorkflowServiceError("invalid_metadata", "workflow metadata is invalid")
    validated = validate_draft_payload(normalized_payload)
    if validated["template_version"] != run.template_version:
        raise WorkflowServiceError("invalid_template", "workflow template is invalid")
    if validated["source_kind"] != run.source_kind:
        raise WorkflowServiceError("invalid_metadata", "workflow metadata is invalid")

    steps = session.scalars(
        select(WorkflowStep)
        .where(WorkflowStep.workflow_id == run.id)
        .order_by(WorkflowStep.position)
    ).all()
    definitions = template["steps"]
    if len(steps) != len(FIXED_STEPS):
        raise WorkflowServiceError("invalid_steps", "workflow step graph is invalid")
    for position, (step, definition) in enumerate(zip(steps, definitions)):
        expected_parameters = {
            "depends_on": definition["depends_on"],
            "parameters": validated["parameters"].get(step.step_key, {}),
        }
        if (
            step.position != position
            or step.step_key != FIXED_STEPS[position]
            or step.status != "waiting"
            or _metadata(step.parameters_json) != expected_parameters
        ):
            raise WorkflowServiceError("invalid_steps", "workflow step graph is invalid")

    step_ids = [step.id for step in steps]
    attempt_count = session.scalar(
        select(func.count()).select_from(WorkflowAttempt).where(
            WorkflowAttempt.step_id.in_(step_ids)
        )
    )
    if attempt_count:
        raise WorkflowServiceError("execution_state_exists", "workflow already has execution state")

    files = session.scalars(
        select(WorkflowFile).where(WorkflowFile.workflow_id == run.id)
    ).all()
    generated = [row for row in files if row.source_kind == "generated"]
    if len(generated) != len(FIXED_STEPS) * 4:
        raise WorkflowServiceError("invalid_manifest", "workflow input manifest is invalid")
    for row in files:
        _read_verified_file(root, row)
    manifest_entries = [_manifest_entry(row) for row in generated]
    expected_manifest = metadata.get("input_manifest")
    if (
        sorted(manifest_entries, key=lambda item: item["logical_path"])
        != expected_manifest
        or _manifest_hash(manifest_entries) != run.input_sha256
    ):
        raise WorkflowServiceError("invalid_manifest", "workflow input manifest is invalid")

    uploads = [row for row in files if row.source_kind == "upload"]
    if run.source_kind == "builtin" and uploads:
        raise WorkflowServiceError("invalid_source", "workflow source is invalid")
    if run.source_kind == "upload":
        if len(uploads) != 1:
            raise WorkflowServiceError("invalid_source", "workflow source is invalid")
        upload_metadata = _metadata(uploads[0].metadata_json)
        if (
            upload_metadata.get("consumed") is not True
            or upload_metadata.get("consumed_by_workflow_id") != run.id
        ):
            raise WorkflowServiceError("invalid_source", "workflow source is invalid")


def _revalidate_file_integrity(
    session: Session,
    root: Path,
    workflow_id: str,
) -> None:
    files = session.scalars(
        select(WorkflowFile)
        .where(WorkflowFile.workflow_id == workflow_id)
        .execution_options(populate_existing=True)
    ).all()
    for row in files:
        _read_verified_file(root, row)


def confirm_workflow(
    session: Session,
    workflow_root: str | os.PathLike[str],
    *,
    owner_id: int,
    workflow_id: str,
) -> WorkflowMutationResult:
    session.rollback()
    run = _reload_owned_workflow(
        session,
        owner_id=owner_id,
        workflow_id=workflow_id,
    )
    if run is None:
        raise WorkflowServiceError("workflow_not_found", "workflow was not found")
    if run.status == "validated":
        return _result(run)
    if run.status != "draft":
        raise WorkflowServiceError("workflow_not_confirmable", "workflow cannot be confirmed")

    input_sha256 = run.input_sha256 or ""
    claimed = _claim_workflow_validation(
        session,
        owner_id=owner_id,
        workflow_id=workflow_id,
        input_sha256=input_sha256,
    )
    if not claimed:
        session.rollback()
        current = _reload_owned_workflow(
            session,
            owner_id=owner_id,
            workflow_id=workflow_id,
        )
        if current is None:
            raise WorkflowServiceError("workflow_not_found", "workflow was not found")
        if current.status == "validated":
            return _result(current)
        if current.status == "validation_failed":
            raise WorkflowServiceError(
                "validation_failed", "workflow validation failed"
            )
        raise WorkflowServiceError(
            "workflow_not_confirmable", "workflow cannot be confirmed"
        )

    try:
        run = _reload_owned_workflow(
            session,
            owner_id=owner_id,
            workflow_id=workflow_id,
        )
        if run is None or run.status != "validating":
            raise RuntimeError("workflow validation claim was lost")
        _validate_workflow(session, _root_path(workflow_root), run)
        _revalidate_file_integrity(session, _root_path(workflow_root), workflow_id)
        transitioned = _transition_workflow_status(
            session,
            owner_id=owner_id,
            workflow_id=workflow_id,
            expected_status="validating",
            target_status="validated",
            input_sha256=input_sha256,
        )
        if not transitioned:
            raise RuntimeError("workflow validation claim was lost")
        session.add(
            WorkflowEvent(
                workflow_id=workflow_id,
                sequence=_next_event_sequence(session, workflow_id),
                event_type="workflow_validated",
                payload_json={"input_sha256": input_sha256},
            )
        )
        session.commit()
    except (InputValidationError, WorkflowServiceError) as exc:
        reason_code = getattr(exc, "code", "invalid_workflow")
        try:
            transitioned = _transition_workflow_status(
                session,
                owner_id=owner_id,
                workflow_id=workflow_id,
                expected_status="validating",
                target_status="validation_failed",
                input_sha256=input_sha256,
            )
            if not transitioned:
                raise RuntimeError("workflow validation claim was lost")
            session.add(
                WorkflowEvent(
                    workflow_id=workflow_id,
                    sequence=_next_event_sequence(session, workflow_id),
                    event_type="validation_failed",
                    payload_json={"reason_code": reason_code},
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        raise WorkflowServiceError(
            "validation_failed", "workflow validation failed"
        ) from exc
    except Exception:
        session.rollback()
        raise

    current = _reload_owned_workflow(
        session,
        owner_id=owner_id,
        workflow_id=workflow_id,
    )
    if current is None:
        raise RuntimeError("validated workflow disappeared after commit")
    return _result(current)
