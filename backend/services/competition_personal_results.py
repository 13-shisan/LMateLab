from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from models_workflow import PersonalVaspRecord, WorkflowRun, canonical_json
from services.competition_results import CompetitionResultService


def _decoded(value: str | dict[str, Any]) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else dict(value)


def personal_record_view(row: PersonalVaspRecord) -> dict[str, Any]:
    return _decoded(row.record_json)


class PersonalResultIndex:
    """Materializes accepted workflow results into an owner-scoped QMOF-like record."""

    def __init__(self, result_service: CompetitionResultService):
        self.result_service = result_service

    @staticmethod
    def _fingerprint(detail: dict[str, Any]) -> str:
        scientific = detail["vasp_detail"]
        identity = {
            "provenance": scientific.get("provenance", {}),
            "structure": scientific.get("structure", {}),
            "properties": scientific.get("properties", {}),
        }
        return hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()

    def sync(self, session: Session, run: WorkflowRun) -> PersonalVaspRecord | None:
        if run.status != "succeeded":
            return None
        detail = self.result_service.detail(run)
        scientific = detail.get("vasp_detail")
        if detail.get("status") != "succeeded" or not isinstance(scientific, dict):
            return None
        properties = scientific.get("properties", {})
        result_row = scientific.get("row", {})
        structure = scientific.get("structure", {})
        elements = list(dict.fromkeys(structure.get("symbols", [])))
        fingerprint = self._fingerprint(detail)
        existing = session.get(PersonalVaspRecord, run.id)
        if existing is not None and existing.artifact_fingerprint == fingerprint:
            return None
        now = datetime.now(timezone.utc)
        record = {
            "id": run.id,
            "formula": str(result_row.get("formula") or run.material),
            "elements": elements,
            "source": "个人计算",
            "source_scope": "personal",
            "workflow_id": run.id,
            "status": "succeeded",
            "bandgap_eV": properties.get("bandgap_eV"),
            "energy": result_row.get("energy"),
            "completed_at": run.updated_at.isoformat() if run.updated_at else None,
            "latest_job_id": detail.get("latest_job_id"),
            "data_kind": "live",
            "vasp_detail": scientific,
            "artifacts": detail.get("artifacts", []),
            "qmof_alignment": {
                "schema": "qmof-compatible-v1",
                "artifact_fingerprint": fingerprint,
                "indexed_at": now.isoformat(),
            },
        }
        values = {
            "owner_id": run.owner_id,
            "artifact_fingerprint": fingerprint,
            "formula": record["formula"],
            "elements_json": elements,
            "energy": record["energy"],
            "bandgap_eV": record["bandgap_eV"],
            "vbm_eV": properties.get("vbm_eV"),
            "cbm_eV": properties.get("cbm_eV"),
            "record_json": record,
            "updated_at": now,
        }
        if existing is None:
            existing = PersonalVaspRecord(workflow_id=run.id, created_at=now, **values)
            session.add(existing)
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        session.flush()
        return existing


def personal_records(session: Session, owner_id: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(PersonalVaspRecord)
        .where(PersonalVaspRecord.owner_id == owner_id)
        .order_by(PersonalVaspRecord.updated_at.desc(), PersonalVaspRecord.workflow_id)
    )
    return [personal_record_view(row) for row in rows]
