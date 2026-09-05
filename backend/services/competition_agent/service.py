from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models_competition_agent import AgentRun
from schemas_competition_agent import AgentRunCreate
from services.competition_agent.catalog import get_template, list_templates
from services.competition_agent.llm_runtime import OpenAICompatibleRuntime
from services.competition_agent.literature import retrieve_for_prompt, selected_records
from services.competition_agent.qoder_runtime import MockQoderRuntime, RealQoderRuntime
from services.competition_agent.tools import (
    prepared_structure_workspace,
    sanitized_workflow_summary,
)
from services.competition_agent.uploads import load_calculation_context, load_context
from services.competition_agent.structure_library import selected_structures
from services.competition_agent.planning import (
    apply_parameter_changes,
    calculation_plan,
    prepare_calculation_workspace,
    structure_analyses,
)
from services.competition_agent.vasp_analysis import analyze_vasp_files


STEP_TEMPLATE = {
    "relax": "2d_relax",
    "scf": "band_scf",
    "band": "band_nscf",
    "dos": "dos",
}
LOGGER = logging.getLogger(__name__)


def infer_request_kind(
    prompt: str,
    *,
    workflow_id: str | None = None,
    calculation_ids: list[str] | None = None,
    files: list[dict[str, object]] | None = None,
    structure_ids: list[str] | None = None,
) -> str:
    lowered = prompt.casefold()
    attached_files = files or []
    has_result_context = bool(
        workflow_id
        or calculation_ids
        or any(item.get("category") == "result" for item in attached_files)
    )
    has_structure_context = bool(
        structure_ids
        or any(item.get("category") == "structure" for item in attached_files)
    )
    explicit_result = re.search(
        r"收敛|算完|完成了吗|计算结果|最终能量|输出结果|outcar|oszicar|vasprun|band\s*gap|费米能级",
        lowered,
    )
    result_action = re.search(r"分析|查看|提取|绘制|画|比较|对比|多少|怎么样|如何", lowered)
    result_subject = re.search(r"结果|能带|态密度|\bdos\b|\bband\b|带隙|能量|磁矩|体系|计算", lowered)
    if has_result_context and (explicit_result or (result_action and result_subject)):
        return "result_analysis"

    calculation_intent = re.search(
        r"计算|新建计算|提交计算|创建任务|结构优化|几何优化|弛豫|relax|scf|生成\s*incar|修改\s*incar",
        lowered,
    )
    calculation_subject = re.search(r"能带|态密度|\bdos\b|\bband\b|incar|参数|优化|体系|材料", lowered)
    if calculation_intent or (has_structure_context and calculation_subject):
        return "calculation_planning"
    return "general_qa"


def _decoded(value: str | None) -> dict[str, object] | None:
    return None if value is None else json.loads(value)


def _provider_error_code(exc: Exception) -> str:
    name = type(exc).__name__.casefold()
    if "timeout" in name:
        return "provider-timeout"
    if "httpstatus" in name:
        return "provider-http-error"
    if "json" in str(exc).casefold() or "response" in str(exc).casefold():
        return "provider-invalid-response"
    return "provider-failed"


def _planning_fallback(plan: dict[str, object], exc: Exception) -> dict[str, object]:
    citations = []
    for collection, kind in (("structures", "structure"), ("templates", "template")):
        for item in plan.get(collection, []):
            if isinstance(item, dict) and item.get("id"):
                citations.append({"kind": kind, "id": str(item["id"])})
    return {
        "provider": "application",
        "summary": "已完成结构检索和计算步骤规划；LLM 增强当前不可用，INCAR 保持模板原始占位值，请人工核验后再使用。",
        "citations": citations,
        "tool_calls": [
            {"name": "search_structure_library", "status": "succeeded"},
            {"name": "anchor_incar_templates", "status": "succeeded"},
            {"name": "llm_parameter_review", "status": "failed"},
        ],
        "workspace": {"plan": plan},
        "parameter_changes": [],
        "advisory_only": True,
        "llm_status": _provider_error_code(exc),
    }


def run_view(run: AgentRun, *, include_request: bool = True) -> dict[str, object]:
    decoded_input = _decoded(run.input_json) or {}
    return {
        "id": run.id,
        "request_kind": run.request_kind,
        "provider": run.provider,
        "status": run.status,
        "workflow_id": run.workflow_id,
        "prompt": run.prompt_text if include_request else "",
        "input": decoded_input if include_request else {},
        "conversation_id": decoded_input.get("conversation_id"),
        "output": _decoded(run.output_json),
        "error_code": run.error_code,
        "approved": run.approved_at is not None,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _conversation_history(
    session: Session,
    owner_id: int,
    conversation_id: str,
) -> list[dict[str, str]]:
    candidates = session.scalars(
        select(AgentRun)
        .where(AgentRun.owner_id == owner_id, AgentRun.status == "succeeded")
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(100)
    )
    turns = []
    for previous in candidates:
        previous_input = _decoded(previous.input_json) or {}
        previous_output = _decoded(previous.output_json) or {}
        if previous_input.get("conversation_id") != conversation_id:
            continue
        summary = previous_output.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            continue
        turns.append({
            "user": previous.prompt_text[:2000],
            "assistant": summary.strip()[:6000],
        })
        if len(turns) == 8:
            break
    return list(reversed(turns))


def _enrich_citations(
    output: dict[str, object],
    tool_payload: dict[str, object],
) -> None:
    sources: dict[tuple[str, str], dict[str, object]] = {}
    for item in tool_payload.get("literature", []):
        if isinstance(item, dict) and item.get("id"):
            sources[("literature", str(item["id"]))] = item
    for item in tool_payload.get("files", []):
        if isinstance(item, dict) and item.get("id") and item.get("category") == "literature":
            sources[("file", str(item["id"]))] = item
    enriched = []
    for citation in output.get("citations", []):
        if not isinstance(citation, dict):
            continue
        key = (str(citation.get("kind") or ""), str(citation.get("id") or ""))
        source = sources.get(key)
        if source is None:
            enriched.append(citation)
            continue
        url = source.get("url")
        doi = source.get("doi")
        if not isinstance(url, str) or not url.startswith("https://"):
            url = f"https://doi.org/{doi}" if isinstance(doi, str) and doi else None
        enriched.append({
            **citation,
            "title": source.get("title") or source.get("name"),
            "authors": source.get("authors", []),
            "year": source.get("year"),
            "doi": doi,
            "url": url,
            "source": source.get("source") or source.get("library_name") or "我的文献库",
        })
    output["citations"] = enriched


def create_run(session: Session, owner_id: int, payload: AgentRunCreate) -> AgentRun:
    conversation_id = payload.conversation_id or str(uuid.uuid4())
    files: list[dict[str, object]] = []
    if payload.request_kind != "template_recommendation":
        files = load_context(session, owner_id, payload.file_ids)
        files.extend(load_calculation_context(
            session, owner_id, payload.calculation_ids, payload.prompt,
        ))
    request_kind = payload.request_kind
    if request_kind == "auto":
        request_kind = infer_request_kind(
            payload.prompt,
            workflow_id=payload.workflow_id,
            calculation_ids=payload.calculation_ids,
            files=files,
            structure_ids=payload.structure_ids,
        )
    literature = selected_records(owner_id, payload.literature_ids)
    literature_tools: list[dict[str, str]] = []
    if payload.search_literature:
        retrieved, literature_tools = retrieve_for_prompt(
            owner_id,
            payload.prompt,
            include_public=True,
        )
        known = {str(item["id"]) for item in literature}
        literature.extend(item for item in retrieved if str(item["id"]) not in known)
    if request_kind == "template_recommendation":
        template = get_template(STEP_TEMPLATE[payload.step_key])
        tool_input = {
            "material_id": payload.material_id,
            "step_key": payload.step_key,
            "templates": (
                [template] if template["material_id"] == payload.material_id else []
            ),
        }
    elif request_kind == "result_analysis":
        tool_input = {}
        if payload.workflow_id:
            tool_input["workflow"] = sanitized_workflow_summary(session, payload.workflow_id, owner_id)
        if files:
            tool_input["files"] = files
            tool_input["analysis_results"] = analyze_vasp_files(tool_input["files"])
    elif request_kind == "calculation_planning":
        tool_input = {
            "files": files,
            "plan": calculation_plan(payload.prompt, files),
        }
    else:
        tool_input = {
            "files": files,
            "structures": selected_structures(payload.structure_ids),
            "analysis_results": analyze_vasp_files(files) + structure_analyses(payload.structure_ids),
        }
        if payload.workflow_id:
            tool_input["workflow"] = sanitized_workflow_summary(session, payload.workflow_id, owner_id)
    if payload.request_kind == "auto":
        tool_input["intent"] = {"requested": "auto", "resolved": request_kind}
    tool_input["conversation_id"] = conversation_id
    history = _conversation_history(session, owner_id, conversation_id)
    if history:
        tool_input["conversation_history"] = history
    if literature:
        tool_input["literature"] = literature
    if literature_tools:
        tool_input["application_tool_calls"] = literature_tools
    run = AgentRun(
        owner_id=owner_id,
        workflow_id=payload.workflow_id,
        request_kind=request_kind,
        provider=os.environ.get("LMATELAB_COMPETITION_AGENT_PROVIDER", "mock"),
        status="queued",
        prompt_text=payload.prompt,
        input_json=tool_input,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def process_next_run(session: Session, runtime=None) -> AgentRun | None:
    selected_runtime = runtime
    provider = getattr(selected_runtime, "provider", None)
    if selected_runtime is None:
        provider = os.environ.get("LMATELAB_COMPETITION_AGENT_PROVIDER", "mock")
    if provider not in {"mock", "qoder", "llm"}:
        raise RuntimeError("unsupported competition Agent provider")
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.status == "queued", AgentRun.provider == provider)
        .order_by(AgentRun.created_at, AgentRun.id)
        .limit(1)
    )
    if run is None:
        return None
    run.status = "running"
    session.commit()
    try:
        if selected_runtime is None:
            if provider == "qoder":
                selected_runtime = RealQoderRuntime()
            elif provider == "llm":
                selected_runtime = OpenAICompatibleRuntime()
            else:
                selected_runtime = MockQoderRuntime()
        tool_payload = _decoded(run.input_json) or {}
        if run.request_kind == "template_recommendation":
            tool_payload["structure"] = prepared_structure_workspace(
                str(tool_payload["material_id"])
            )
        plan = tool_payload.get("plan")
        if isinstance(plan, dict) and plan.get("needs_upload"):
            output = {
                "provider": "application",
                "summary": f"结构库中未找到 {plan.get('material_formula') or '可识别材料'}，请先上传结构文件。",
                "citations": [],
                "tool_calls": [{"name": "search_structure_library", "status": "succeeded"}],
                "workspace": {"plan": plan},
                "advisory_only": True,
                "needs_upload": True,
            }
        else:
            try:
                output = selected_runtime.run(
                    request_kind=run.request_kind,
                    prompt=run.prompt_text,
                    tool_payload=tool_payload,
                )
            except Exception as exc:
                if not isinstance(plan, dict):
                    raise
                LOGGER.exception("competition Agent LLM enhancement %s failed", run.id)
                output = _planning_fallback(plan, exc)
            if isinstance(plan, dict):
                apply_parameter_changes(plan, output.get("parameter_changes"))
                workspace = output.get("workspace") if isinstance(output.get("workspace"), dict) else {}
                structure = prepare_calculation_workspace(plan)
                output["workspace"] = {**workspace, "plan": plan, "structure": structure}
        application_calls = tool_payload.get("application_tool_calls")
        if isinstance(application_calls, list):
            output["tool_calls"] = [*application_calls, *output.get("tool_calls", [])]
        _enrich_citations(output, tool_payload)
        run.output_json = output
        run.status = "succeeded"
        run.error_code = None
    except Exception as exc:
        LOGGER.exception("competition Agent run %s failed", run.id)
        run.output_json = None
        run.status = "failed"
        run.error_code = _provider_error_code(exc)
    run.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(run)
    return run


def delete_conversation(session: Session, owner_id: int, conversation_id: str) -> int:
    rows = []
    for run in session.scalars(
        select(AgentRun)
        .where(AgentRun.owner_id == owner_id)
        .order_by(AgentRun.created_at)
    ):
        if (_decoded(run.input_json) or {}).get("conversation_id") == conversation_id:
            rows.append(run)
    if any(run.status in {"queued", "running"} for run in rows):
        raise ValueError("active conversation cannot be deleted")
    for run in rows:
        session.delete(run)
    session.commit()
    return len(rows)


def approve_run(session: Session, run: AgentRun, operator_id: int) -> AgentRun:
    if run.owner_id != operator_id or run.status != "succeeded":
        raise ValueError("Agent run cannot be approved")
    run.approved_by_id = operator_id
    run.approved_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(run)
    return run
