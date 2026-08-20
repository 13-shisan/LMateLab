from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from models_workflow import WorkflowRun, WorkflowTemplate, canonical_json


_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024


class BundleError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _metadata(value: str | Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _timestamp(value) -> str | None:
    return value.isoformat() if value is not None else None


def _safe_release_manifest(releases_root: Path, commit: str) -> dict[str, Any]:
    if _COMMIT_RE.fullmatch(commit or "") is None:
        raise BundleError("release_commit_invalid", "release identity is invalid")
    root = releases_root.resolve(strict=True)
    release = releases_root / commit
    try:
        release_identity = release.lstat()
        resolved_release = release.resolve(strict=True)
    except OSError:
        raise BundleError("release_manifest_missing", "release manifest is unavailable") from None
    if stat.S_ISLNK(release_identity.st_mode) or not stat.S_ISDIR(release_identity.st_mode):
        raise BundleError("release_manifest_invalid", "release manifest is invalid")
    if resolved_release != root / commit or root not in resolved_release.parents:
        raise BundleError("release_manifest_invalid", "release manifest is invalid")

    manifest_path = release / "manifest.txt"
    digest_path = release / "manifest.sha256"
    for path in (manifest_path, digest_path):
        try:
            identity = path.lstat()
        except OSError:
            raise BundleError("release_manifest_missing", "release manifest is unavailable") from None
        if stat.S_ISLNK(identity.st_mode) or not stat.S_ISREG(identity.st_mode):
            raise BundleError("release_manifest_invalid", "release manifest is invalid")
        if identity.st_size <= 0 or identity.st_size > _MAX_MANIFEST_BYTES:
            raise BundleError("release_manifest_invalid", "release manifest is invalid")

    try:
        manifest_bytes = manifest_path.read_bytes()
        digest_text = digest_path.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        raise BundleError("release_manifest_invalid", "release manifest is invalid") from None
    calculated = hashlib.sha256(manifest_bytes).hexdigest()
    digest_parts = digest_text.strip().split()
    if len(digest_parts) != 2 or digest_parts[1] != "manifest.txt" or digest_parts[0] != calculated:
        raise BundleError("release_manifest_hash_mismatch", "release manifest changed")

    try:
        manifest_text = manifest_bytes.decode("utf-8")
    except UnicodeError:
        raise BundleError("release_manifest_invalid", "release manifest is invalid") from None
    entries = []
    for line in manifest_text.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or _SHA256_RE.fullmatch(parts[0]) is None:
            raise BundleError("release_manifest_invalid", "release manifest is invalid")
        relative_path = parts[1].lstrip("*")
        candidate = Path(relative_path)
        if candidate.is_absolute() or not relative_path or ".." in candidate.parts:
            raise BundleError("release_manifest_invalid", "release manifest is invalid")
        entries.append({"path": candidate.as_posix(), "sha256": parts[0]})
    if not entries:
        raise BundleError("release_manifest_invalid", "release manifest is invalid")
    return {
        "commit": commit,
        "manifest_sha256": calculated,
        "manifest": entries,
    }


def _scheduler_payload(metadata: Mapping[str, Any]) -> dict[str, Any]:
    value = metadata.get("scheduler_observation")
    if not isinstance(value, Mapping):
        return {}
    keys = (
        "job_id",
        "state",
        "raw_state",
        "exit_code",
        "node_list",
        "reason",
        "stale",
        "stale_since",
        "error_code",
        "observed_at",
        "started_at",
        "finished_at",
    )
    return {key: value.get(key) for key in keys if key in value}


def _acceptance_payload(metadata: Mapping[str, Any]) -> dict[str, Any] | None:
    value = metadata.get("scientific_acceptance")
    return dict(value) if isinstance(value, Mapping) else None


def _reject_absolute_path_strings(value: Any) -> None:
    if isinstance(value, str):
        if value.startswith(("/", "\\\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
            raise BundleError("bundle_absolute_path", "evidence bundle contains an unsafe path")
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_absolute_path_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_absolute_path_strings(item)


def build_evidence_bundle(
    session: Session,
    run: WorkflowRun,
    *,
    releases_root: Path,
    verify_file: Callable[[Any], Any],
    provenance: Mapping[str, Any],
) -> bytes:
    template = session.scalar(
        select(WorkflowTemplate).where(
            WorkflowTemplate.template_key == "mos2",
            WorkflowTemplate.version == run.template_version,
        )
    )
    if template is None:
        raise BundleError("template_missing", "workflow template is unavailable")

    run_metadata = _metadata(run.metadata_json)
    steps = []
    for step in sorted(run.steps, key=lambda item: item.position):
        attempts = []
        for attempt in sorted(step.attempts, key=lambda item: item.attempt_number):
            metadata = _metadata(attempt.metadata_json)
            attempts.append(
                {
                    "id": attempt.id,
                    "number": attempt.attempt_number,
                    "status": attempt.status,
                    "job_id": attempt.slurm_job_id,
                    "started_at": _timestamp(attempt.started_at),
                    "finished_at": _timestamp(attempt.finished_at),
                    "created_at": _timestamp(attempt.created_at),
                    "updated_at": _timestamp(attempt.updated_at),
                    "scheduler": _scheduler_payload(metadata),
                    "scientific_acceptance": _acceptance_payload(metadata),
                    "scientific_acceptance_sha256": metadata.get(
                        "scientific_acceptance_sha256"
                    ),
                }
            )
        steps.append(
            {
                "key": step.step_key,
                "position": step.position,
                "status": step.status,
                "parameters": _metadata(step.parameters_json),
                "created_at": _timestamp(step.created_at),
                "updated_at": _timestamp(step.updated_at),
                "attempts": attempts,
            }
        )

    files = []
    for row in sorted(run.files, key=lambda item: (item.relative_path, item.id)):
        verified = verify_file(row)
        metadata = _metadata(row.metadata_json)
        files.append(
            {
                "id": row.id,
                "attempt_id": row.attempt_id,
                "relative_path": verified.relative_path,
                "logical_path": metadata.get("logical_path"),
                "source_kind": row.source_kind,
                "role": metadata.get("input_role") or metadata.get("output_role"),
                "step_key": metadata.get("step_key"),
                "size_bytes": verified.size_bytes,
                "sha256": verified.sha256,
            }
        )

    events = [
        {
            "sequence": event.sequence,
            "type": event.event_type,
            "payload": _metadata(event.payload_json),
            "created_at": _timestamp(event.created_at),
        }
        for event in sorted(run.events, key=lambda item: item.sequence)
    ]
    release = _safe_release_manifest(releases_root, run.release_commit or "")
    payload = {
        "schema": "lmatelab-107cup-evidence-v1",
        "workflow": {
            "id": run.id,
            "material": run.material,
            "creator": run.owner.alias or run.owner.name,
            "source_kind": run.source_kind,
            "status": run.status,
            "template_version": run.template_version,
            "input_sha256": run.input_sha256,
            "created_at": _timestamp(run.created_at),
            "updated_at": _timestamp(run.updated_at),
        },
        "release": release,
        "template": {
            "key": template.template_key,
            "version": template.version,
            "definition": _metadata(template.definition_json),
        },
        "inputs": {
            "normalized_payload": run_metadata.get("normalized_payload"),
            "manifest": run_metadata.get("input_manifest", []),
            "structure_summary": run_metadata.get("structure_summary", {}),
        },
        "steps": steps,
        "events": events,
        "files": files,
        "result_provenance": dict(provenance),
    }
    _reject_absolute_path_strings(payload)
    encoded_without_digest = canonical_json(payload).encode("utf-8")
    payload["payload_sha256"] = hashlib.sha256(encoded_without_digest).hexdigest()
    return canonical_json(payload).encode("utf-8") + b"\n"
