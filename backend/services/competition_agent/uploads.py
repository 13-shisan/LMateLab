from __future__ import annotations

import hashlib
import io
import json
import os
import re
import uuid
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from models_workflow import WorkflowFile


MAX_AGENT_FILE_BYTES = 20 * 1024 * 1024
MAX_CONTEXT_BYTES = 1024 * 1024
UPLOAD_CATEGORIES = {"result", "structure", "incar-template", "literature"}
EXAMPLE_GROUPS = {
    "cr2c12o6f6_scf": "Dawn5 / Cr2C12O6F6 SCF",
    "cr2c12se6f6_scf": "Dawn5 / Cr2C12Se6F6 SCF",
}
ALLOWED_SUFFIXES = {
    ".txt", ".md", ".json", ".csv", ".cif", ".vasp", ".poscar",
    ".incar", ".outcar", ".xml", ".yaml", ".yml", ".log", ".dat", ".pdf",
}


class AgentUploadError(ValueError):
    pass


def _safe_calculation_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9:._-]{1,160}", value):
        raise AgentUploadError("invalid calculation id")
    return value


def upload_root() -> Path:
    configured = os.environ.get("LMATELAB_AGENT_UPLOADS_ROOT")
    return Path(configured or "data/competition-agent/uploads").resolve()


def _safe_name(filename: str) -> str:
    name = Path(filename).name
    if not name or name != filename or "\x00" in name:
        raise AgentUploadError("invalid filename")
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES and name.upper() not in {
        "INCAR", "OUTCAR", "POSCAR", "CONTCAR", "KPOINTS", "OSZICAR",
        "PROCAR", "DOSCAR", "EIGENVAL", "IBZKPT", "XDATCAR", "REPORT",
    }:
        raise AgentUploadError("unsupported file type")
    return name


def _metadata(row: WorkflowFile) -> dict[str, object]:
    return json.loads(row.metadata_json) if isinstance(row.metadata_json, str) else row.metadata_json


def _extract_text(name: str, content: bytes, category: str) -> str:
    if name.lower().endswith(".pdf"):
        if category != "literature":
            raise AgentUploadError("PDF files are only accepted in the literature library")
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > 300:
                raise AgentUploadError("PDF exceeds the 300 page limit")
            return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()
        except AgentUploadError:
            raise
        except Exception as exc:
            raise AgentUploadError("PDF text extraction failed") from exc
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgentUploadError("text files must use UTF-8 encoding") from exc


def store_upload(
    session: Session,
    owner_id: int,
    filename: str,
    content: bytes,
    *,
    category: str = "result",
    library_name: str = "我的文献库",
    calculation_id: str | None = None,
    group_name: str | None = None,
) -> WorkflowFile:
    name = _safe_name(filename)
    if category not in UPLOAD_CATEGORIES:
        raise AgentUploadError("unsupported upload category")
    if not content or len(content) > MAX_AGENT_FILE_BYTES:
        raise AgentUploadError("file must be between 1 byte and 20 MiB")
    extracted_text = _extract_text(name, content, category)
    if category == "literature" and not extracted_text:
        raise AgentUploadError("literature file contains no extractable text")
    clean_library = library_name.strip()[:80] or "我的文献库"
    clean_calculation_id = None
    clean_group_name = None
    if category == "result":
        clean_calculation_id = _safe_calculation_id(calculation_id or str(uuid.uuid4()))
        clean_group_name = (group_name or name).strip()[:160] or name
    file_id = str(uuid.uuid4())
    root = upload_root()
    directory = root / str(owner_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = directory / file_id
    path.write_bytes(content)
    path.chmod(0o600)
    row = WorkflowFile(
        id=file_id,
        owner_id=owner_id,
        relative_path=f"agent/{owner_id}/{file_id}",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        source_kind="agent-upload",
        metadata_json={
            "original_filename": name,
            "category": category,
            "library_name": clean_library if category == "literature" else None,
            "calculation_id": clean_calculation_id,
            "group_name": clean_group_name,
            "extracted_text": extracted_text[:MAX_CONTEXT_BYTES] if name.lower().endswith(".pdf") else None,
            "media_type": "application/pdf" if name.lower().endswith(".pdf") else "text/plain",
        },
    )
    try:
        session.add(row)
        session.commit()
        session.refresh(row)
    except Exception:
        session.rollback()
        path.unlink(missing_ok=True)
        raise
    return row


def list_uploads(session: Session, owner_id: int) -> list[WorkflowFile]:
    _ensure_builtin_examples(session, owner_id)
    rows = list(session.scalars(select(WorkflowFile).where(
        WorkflowFile.owner_id == owner_id,
        WorkflowFile.source_kind.in_(("agent-upload", "agent-example")),
    ).order_by(WorkflowFile.created_at.desc(), WorkflowFile.id.asc())))
    uploads = [row for row in rows if row.source_kind == "agent-upload"]
    examples = [row for row in rows if row.source_kind == "agent-example"]
    # Built-in examples retain the API's newest-first display semantics while
    # avoiding timestamp and UUID tie-breaking differences across databases.
    case_order = {
        case_id: index
        for index, case_id in enumerate(reversed(tuple(EXAMPLE_GROUPS)))
    }
    file_order = {
        name: index
        for index, name in enumerate(("OUTCAR", "OSZICAR", "POSCAR", "INCAR", "KPOINTS"))
    }

    def example_order(row: WorkflowFile) -> tuple[int, int, str]:
        metadata = _metadata(row)
        example_key = str(metadata.get("example_key") or "")
        case_id, _, filename = example_key.partition("/")
        return (
            case_order.get(case_id, len(case_order)),
            file_order.get(filename, len(file_order)),
            row.id,
        )

    return uploads + sorted(examples, key=example_order)


def _ensure_builtin_examples(session: Session, owner_id: int) -> None:
    if os.environ.get("LMATELAB_AGENT_EXAMPLES_ENABLED", "0") != "1":
        return
    existing = {
        str(_metadata(row).get("example_key"))
        for row in session.scalars(select(WorkflowFile).where(
            WorkflowFile.owner_id == owner_id,
            WorkflowFile.source_kind == "agent-example",
        ))
    }
    examples_root = Path(__file__).resolve().parents[2] / "competition_examples" / "dawn5"
    created_paths: list[Path] = []
    try:
        for case_id, group_name in EXAMPLE_GROUPS.items():
            case_root = examples_root / case_id
            for filename in ("OUTCAR", "OSZICAR", "POSCAR", "INCAR", "KPOINTS"):
                example_key = f"{case_id}/{filename}"
                if example_key in existing:
                    continue
                content = (case_root / filename).read_bytes()
                file_id = str(uuid.uuid4())
                directory = upload_root() / str(owner_id)
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                directory.chmod(0o700)
                path = directory / file_id
                path.write_bytes(content)
                path.chmod(0o600)
                created_paths.append(path)
                session.add(WorkflowFile(
                    id=file_id,
                    owner_id=owner_id,
                    relative_path=f"agent/{owner_id}/{file_id}",
                    size_bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    source_kind="agent-example",
                    metadata_json={
                        "original_filename": filename,
                        "category": "result",
                        "calculation_id": f"example:{case_id}",
                        "group_name": group_name,
                        "example_key": example_key,
                        "provenance": "sanitized Dawn5 completed SCF result excerpt",
                        "media_type": "text/plain",
                    },
                ))
        session.commit()
    except Exception:
        session.rollback()
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise


def _row_calculation_id(row: WorkflowFile) -> str | None:
    metadata = _metadata(row)
    if metadata.get("category") != "result":
        return None
    configured = metadata.get("calculation_id")
    if isinstance(configured, str) and configured:
        return configured
    example_key = metadata.get("example_key")
    if isinstance(example_key, str) and "/" in example_key:
        return f"example:{example_key.split('/', 1)[0]}"
    group_name = metadata.get("group_name")
    if isinstance(group_name, str) and group_name:
        digest = hashlib.sha256(group_name.encode("utf-8")).hexdigest()[:20]
        return f"legacy:{digest}"
    return f"file:{row.id}"


def _load_rows_context(
    owner_id: int,
    rows: list[WorkflowFile],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    total = 0
    for row in rows:
        path = upload_root() / str(owner_id) / row.id
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row.sha256:
            raise AgentUploadError("uploaded file integrity check failed")
        metadata = _metadata(row)
        extracted = metadata.get("extracted_text")
        if isinstance(extracted, str):
            content = extracted.encode("utf-8")
        remaining = MAX_CONTEXT_BYTES - total
        if remaining <= 0:
            raise AgentUploadError("selected files exceed analysis context limit")
        if len(content) > remaining:
            half = max(1, remaining // 2)
            content = content[:half] + b"\n\n[... middle omitted by LMateLab ...]\n\n" + content[-half:]
        total += len(content)
        result.append({
            "kind": "file",
            "id": row.id,
            "name": metadata.get("original_filename", row.id),
            "sha256": row.sha256,
            "content": content.decode("utf-8"),
            "category": metadata.get("category", "result"),
            "library_name": metadata.get("library_name"),
            "calculation_id": _row_calculation_id(row),
            "group_name": metadata.get("group_name"),
        })
    return result


def load_context(session: Session, owner_id: int, file_ids: Iterable[str]) -> list[dict[str, object]]:
    ids = list(dict.fromkeys(file_ids))
    if not ids:
        return []
    rows = list(session.scalars(select(WorkflowFile).where(
        WorkflowFile.id.in_(ids),
        WorkflowFile.owner_id == owner_id,
        WorkflowFile.source_kind.in_(("agent-upload", "agent-example")),
    )))
    if len(rows) != len(ids):
        raise AgentUploadError("one or more files are unavailable")
    by_id = {row.id: row for row in rows}
    return _load_rows_context(owner_id, [by_id[file_id] for file_id in ids])


def _analysis_file_priority(prompt: str) -> tuple[str, ...]:
    normalized = prompt.casefold()
    if any(token in normalized for token in ("能带", "band", "带隙", "费米")):
        return ("EIGENVAL", "PROCAR", "VASPRUN.XML", "KPOINTS", "OUTCAR", "INCAR")
    if any(token in normalized for token in ("态密度", "dos", "density of states")):
        return ("DOSCAR", "VASPRUN.XML", "INCAR", "OUTCAR")
    if any(token in normalized for token in ("结构", "晶格", "键长", "structure", "lattice", "geometry")):
        return ("CONTCAR", "POSCAR", "OUTCAR", "INCAR")
    if any(token in normalized for token in ("收敛", "能量", "力", "磁矩", "converg", "energy", "force", "magnet")):
        return ("OUTCAR", "OSZICAR", "INCAR")
    return ("OUTCAR", "OSZICAR", "INCAR", "CONTCAR", "POSCAR", "VASPRUN.XML")


def load_calculation_context(
    session: Session,
    owner_id: int,
    calculation_ids: Iterable[str],
    prompt: str,
) -> list[dict[str, object]]:
    ids = list(dict.fromkeys(calculation_ids))
    if not ids:
        return []
    rows = list(session.scalars(select(WorkflowFile).where(
        WorkflowFile.owner_id == owner_id,
        WorkflowFile.source_kind.in_(("agent-upload", "agent-example")),
    )))
    grouped: dict[str, list[WorkflowFile]] = {}
    for row in rows:
        calculation_id = _row_calculation_id(row)
        if calculation_id in ids:
            grouped.setdefault(calculation_id, []).append(row)
    if any(calculation_id not in grouped for calculation_id in ids):
        raise AgentUploadError("one or more calculation directories are unavailable")
    priority = _analysis_file_priority(prompt)
    selected: list[WorkflowFile] = []
    for calculation_id in ids:
        by_name = {
            str(_metadata(row).get("original_filename", row.id)).upper(): row
            for row in grouped[calculation_id]
        }
        selected.extend(by_name[name] for name in priority if name in by_name)
        if not any(name in by_name for name in priority):
            selected.extend(grouped[calculation_id][:4])
    return _load_rows_context(owner_id, selected)


def calculation_views(rows: Iterable[WorkflowFile]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        calculation_id = _row_calculation_id(row)
        if calculation_id is None:
            continue
        metadata = _metadata(row)
        entry = grouped.setdefault(calculation_id, {
            "id": calculation_id,
            "name": metadata.get("group_name") or metadata.get("original_filename") or calculation_id,
            "builtin_example": row.source_kind == "agent-example",
            "files": [],
        })
        entry["files"].append(upload_view(row))
    return list(grouped.values())


def upload_view(row: WorkflowFile) -> dict[str, object]:
    metadata = _metadata(row)
    return {
        "id": row.id,
        "name": metadata.get("original_filename", row.id),
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "created_at": row.created_at,
        "category": metadata.get("category", "result"),
        "library_name": metadata.get("library_name"),
        "media_type": metadata.get("media_type", "text/plain"),
        "group_name": metadata.get("group_name"),
        "calculation_id": _row_calculation_id(row),
        "builtin_example": row.source_kind == "agent-example",
    }
