from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models_competition_agent import AgentRun
from schemas_competition_agent import AgentRunCreate
from services.competition_agent.catalog import get_template, list_templates
from services.competition_agent.qoder_runtime import MockQoderRuntime
from services.competition_agent.tools import (
    prepared_structure_workspace,
    sanitized_workflow_summary,
)


STEP_TEMPLATE = {
    "relax": "2d_relax",
    "scf": "band_scf",
    "band": "band_nscf",
    "dos": "dos",
}


def _decoded(value: str | None) -> dict[str, object] | None:
    return None if value is None else json.loads(value)


def run_view(run: AgentRun, *, include_request: bool = True) -> dict[str, object]:
    return {
        "id": run.id,
        "request_kind": run.request_kind,
        "provider": run.provider,
        "status": run.status,
        "workflow_id": run.workflow_id,
        "prompt": run.prompt_text if include_request else "",
        "input": (_decoded(run.input_json) or {}) if include_request else {},
        "output": _decoded(run.output_json),
        "error_code": run.error_code,
        "approved": run.approved_at is not None,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def create_run(session: Session, owner_id: int, payload: AgentRunCreate) -> AgentRun:
    if payload.request_kind == "template_recommendation":
        template = get_template(STEP_TEMPLATE[payload.step_key])
        tool_input = {
            "material_id": payload.material_id,
            "step_key": payload.step_key,
            "templates": (
                [template] if template["material_id"] == payload.material_id else []
            ),
        }
    else:
        tool_input = {
            "workflow": sanitized_workflow_summary(session, payload.workflow_id, owner_id),
        }
    run = AgentRun(
        owner_id=owner_id,
        workflow_id=payload.workflow_id,
        request_kind=payload.request_kind,
        provider="mock",
        status="queued",
        prompt_text=payload.prompt,
        input_json=tool_input,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def process_next_run(session: Session, runtime=None) -> AgentRun | None:
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.status == "queued", AgentRun.provider == "mock")
        .order_by(AgentRun.created_at, AgentRun.id)
        .limit(1)
    )
    if run is None:
        return None
    run.status = "running"
    session.commit()
    try:
        tool_payload = _decoded(run.input_json) or {}
        if run.request_kind == "template_recommendation":
            tool_payload["structure"] = prepared_structure_workspace(
                str(tool_payload["material_id"])
            )
        output = (runtime or MockQoderRuntime()).run(
            request_kind=run.request_kind,
            prompt=run.prompt_text,
            tool_payload=tool_payload,
        )
        run.output_json = output
        run.status = "succeeded"
        run.error_code = None
    except Exception:
        run.output_json = None
        run.status = "failed"
        run.error_code = "provider-failed"
    run.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(run)
    return run


def approve_run(session: Session, run: AgentRun, operator_id: int) -> AgentRun:
    if run.owner_id != operator_id or run.status != "succeeded":
        raise ValueError("Agent run cannot be approved")
    run.approved_by_id = operator_id
    run.approved_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(run)
    return run
