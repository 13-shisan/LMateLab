from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models_workflow import WorkflowRun, WorkflowStep
from services.competition_agent.structures import build_structure


class AgentToolError(ValueError):
    pass


def prepared_structure_workspace(material_id: str) -> dict[str, object]:
    """Build a bounded structure using application code, never provider tools."""
    result = build_structure(material_id=material_id)
    result["files"] = {
        name: content
        for name, content in result["files"].items()
        if name != "POTCAR"
    }
    return result


def sanitized_workflow_summary(
    session: Session,
    workflow_id: str,
    owner_id: int,
) -> dict[str, object]:
    workflow = session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.id == workflow_id,
            WorkflowRun.owner_id == owner_id,
        )
    )
    if workflow is None:
        raise AgentToolError("workflow is unavailable")
    steps = list(
        session.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow.id)
            .order_by(WorkflowStep.position)
        )
    )
    return {
        "id": workflow.id,
        "material": workflow.material,
        "template_version": workflow.template_version,
        "status": workflow.status,
        "steps": [{"key": step.step_key, "status": step.status} for step in steps],
    }
