from __future__ import annotations

import os
import json
import importlib.util
import re
from dataclasses import dataclass
from typing import Any, Mapping

from services.competition_agent.controlled_qoder_tools import (
    CONTROLLED_QODER_TOOL_NAMES,
    MCP_SERVER_NAME,
    ControlledQoderToolSession,
    build_sdk_mcp_server,
)
from services.competition_agent.planning import validated_parameter_changes


DISABLED_BUILTIN_TOOLS = ("Bash", "Write", "Edit", "Read", "Glob", "WebFetch")


@dataclass(frozen=True)
class QoderRuntimeConfig:
    permission_mode: str = "dontAsk"
    yolo: bool = False
    allowed_builtin_tools: tuple[str, ...] = ()
    disabled_builtin_tools: tuple[str, ...] = DISABLED_BUILTIN_TOOLS
    model: str | None = None
    auth_mode: str = "pat"
    max_turns: int = 8
    timeout_seconds: float = 120.0

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None):
        values = os.environ if environ is None else environ
        return cls(
            model=values.get("LMATELAB_QODER_MODEL") or None,
            auth_mode=values.get("LMATELAB_QODER_AUTH_MODE", "pat"),
            max_turns=max(1, min(8, int(values.get("LMATELAB_QODER_MAX_TURNS", "8")))),
            timeout_seconds=float(values.get("LMATELAB_QODER_TIMEOUT_SECONDS", "120")),
        )


def qoder_engine_status(
    environ: Mapping[str, str] | None = None,
    *,
    managed_status: Mapping[str, object] | None = None,
) -> dict[str, object]:
    values = os.environ if environ is None else environ
    if managed_status is None and values.get("LMATELAB_QODER_MANAGEMENT_ENABLED") == "1":
        try:
            from services.qoder_management import qoder_status

            managed_status = qoder_status()
        except (OSError, RuntimeError):
            managed_status = None
    auth_mode = values.get("LMATELAB_QODER_AUTH_MODE", "pat")
    installed = (
        managed_status.get("installed") is True
        if managed_status is not None
        else importlib.util.find_spec("qodercn_agent_sdk") is not None
    )
    if auth_mode == "cli":
        authenticated = (
            managed_status.get("authenticated") is True
            if managed_status is not None
            else values.get("LMATELAB_QODER_CONNECTED", "0") == "1"
        )
    elif auth_mode == "pat":
        authenticated = bool(values.get("QODERCN_PERSONAL_ACCESS_TOKEN", "").strip())
    else:
        authenticated = False
    network_authorized = values.get("LMATELAB_QODER_REAL_NETWORK_AUTHORIZED") == "1"
    available = installed and authenticated and network_authorized
    if not installed:
        reason = "sdk-not-installed"
    elif auth_mode not in {"cli", "pat"}:
        reason = "unsupported-auth-mode"
    elif not authenticated:
        reason = "not-authenticated"
    elif not network_authorized:
        reason = "network-not-authorized"
    else:
        reason = None
    return {
        "engine_available": available,
        "engine_unavailable_reason": reason,
        "network_authorized": network_authorized,
        "engine_authenticated": authenticated,
        "sdk_installed": installed,
    }


class MockQoderRuntime:
    provider = "mock"

    def run(
        self,
        *,
        request_kind: str,
        prompt: str,
        tool_payload: dict[str, object],
    ) -> dict[str, object]:
        if request_kind == "template_recommendation":
            templates = list(tool_payload.get("templates", []))
            recommended = templates[0] if templates else None
            template_id = recommended.get("id") if isinstance(recommended, dict) else None
            summary = (
                f"建议使用受控模板 {template_id}。请由 Operator 核对后在现有工作流中应用。"
                if template_id
                else "当前受控目录中没有适用模板。"
            )
            citations = [{"kind": "template", "id": template_id}] if template_id else []
            structure = tool_payload.get("structure")
            workspace = {"structure": structure} if isinstance(structure, dict) else {}
            tool_calls = ([{"name": "build_curated_structure", "status": "succeeded"}]
                          if structure else [])
        elif request_kind == "calculation_planning":
            plan = tool_payload.get("plan") if isinstance(tool_payload.get("plan"), dict) else {}
            structures = plan.get("structures", [])
            templates = plan.get("templates", [])
            summary = f"已匹配 {len(structures)} 个结构并生成 {len(templates)} 步计算建议，请核验后提交新建计算。"
            citations = [
                {"kind": kind, "id": str(item["id"])}
                for collection, kind in ((structures, "structure"), (templates, "template"))
                for item in collection
                if isinstance(item, dict) and item.get("id")
            ]
            workspace = {"plan": plan}
            tool_calls = [
                {"name": "search_structure_library", "status": "succeeded"},
                {"name": "anchor_incar_templates", "status": "succeeded"},
            ]
        else:
            workflow = tool_payload.get("workflow")
            workflow_id = workflow.get("id") if isinstance(workflow, dict) else None
            status = workflow.get("status") if isinstance(workflow, dict) else "unknown"
            summary = (
                f"工作流 {workflow_id} 的权威记录状态为 {status}。"
                "本分析只解释持久化证据，不替代科学验收。"
            )
            citations = [{"kind": "workflow", "id": workflow_id}] if workflow_id else []
            workspace = {}
            tool_calls = [{"name": "read_workflow_summary", "status": "succeeded"}]
        return {
            "provider": self.provider,
            "summary": summary,
            "citations": citations,
            "tool_calls": tool_calls,
            "workspace": workspace,
            "advisory_only": True,
            "prompt_length": len(prompt),
        }


class RealQoderRuntime:
    provider = "qoder"

    def __init__(self, environ: Mapping[str, str] | None = None):
        self._environ = os.environ if environ is None else environ
        self.config = QoderRuntimeConfig.from_environ(self._environ)

    def run(
        self,
        *,
        request_kind: str,
        prompt: str,
        tool_payload: dict[str, object],
    ) -> dict[str, object]:
        if self._environ.get("LMATELAB_QODER_REAL_NETWORK_AUTHORIZED") != "1":
            raise RuntimeError("real Qoder runtime is not authorized")
        if self.config.auth_mode not in {"pat", "cli"}:
            raise RuntimeError("unsupported Qoder authentication mode")
        if self.config.auth_mode == "pat" and not self._environ.get("QODERCN_PERSONAL_ACCESS_TOKEN"):
            raise RuntimeError("Qoder CN personal access token is unavailable")
        try:
            import anyio
            import qodercn_agent_sdk as sdk
        except ImportError as exc:
            raise RuntimeError("qodercn-agent-sdk is not installed") from exc

        system_prompt = (
            "You are LMateLab's controlled calculation-planning Agent. Decide which exposed "
            "LMateLab read-only tools are needed, inspect only their returned data, and prepare "
            "an advisory VASP calculation draft. For calculation planning, inspect the mounted "
            "structure or search the structure library, then call prepare_workflow_draft. For "
            "result analysis, call the relevant VASP result and workflow summary tools. Never "
            "claim that a calculation ran. Never submit, cancel, mutate, execute VASP, use a "
            "scheduler, access arbitrary files, use shell, or use the web. Return exactly one "
            "JSON object with summary, citations, parameter_changes, and advisory_only. "
            "advisory_only must be true. parameter_changes may use only editable parameters "
            "returned by prepare_workflow_draft. The user and LMateLab must validate every draft."
        )
        tool_session = ControlledQoderToolSession(tool_payload)
        mcp_server = build_sdk_mcp_server(tool_session, sdk)
        request_payload = {
            "request_kind": request_kind,
            "user_prompt": prompt,
            "authorized_context_index": tool_session.context_index(),
        }

        async def invoke() -> str:
            options = sdk.QoderAgentOptions(
                auth=(
                    sdk.qodercli_auth()
                    if self.config.auth_mode == "cli"
                    else sdk.access_token_from_env()
                ),
                system_prompt=system_prompt,
                tools=[],
                mcp_servers={MCP_SERVER_NAME: mcp_server},
                allowed_tools=[
                    f"mcp__{MCP_SERVER_NAME}__{name}"
                    for name in CONTROLLED_QODER_TOOL_NAMES
                ],
                allowed_mcp_server_names=[MCP_SERVER_NAME],
                strict_mcp_config=True,
                disallowed_tools=list(self.config.disabled_builtin_tools),
                permission_mode=self.config.permission_mode,
                allow_dangerously_skip_permissions=False,
                max_turns=self.config.max_turns,
                model=self.config.model,
                skills=[],
                security_scan={
                    "l1_static_check": False,
                    "l2_lightweight_scan": False,
                    "l3_deep_scan": False,
                },
            )
            text_parts: list[str] = []
            result_text: str | None = None
            with anyio.fail_after(self.config.timeout_seconds):
                async for message in sdk.query(
                    prompt=json.dumps(request_payload, ensure_ascii=False),
                    options=options,
                ):
                    if isinstance(message, sdk.AssistantMessage):
                        text_parts.extend(
                            block.text for block in message.content if isinstance(block, sdk.TextBlock)
                        )
                    elif isinstance(message, sdk.ResultMessage):
                        if message.is_error:
                            raise RuntimeError("Qoder returned an error result")
                        result_text = message.result
            return result_text or "".join(text_parts)

        raw = anyio.run(invoke)
        return self._validated_output(
            raw,
            request_kind,
            tool_payload,
            allowed_ids=tool_session.exposed_ids,
            tool_calls=tool_session.calls,
        )

    @staticmethod
    def _validated_output(
        raw: str,
        request_kind: str,
        tool_payload: dict[str, object],
        *,
        allowed_ids: set[tuple[str, str]] | None = None,
        tool_calls: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        candidate = raw.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL)
        if fenced:
            candidate = fenced.group(1)
        try:
            value = json.loads(candidate)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Qoder returned invalid JSON") from exc
        if not isinstance(value, dict) or value.get("advisory_only") is not True:
            raise RuntimeError("Qoder response is not advisory-only")
        if not isinstance(value.get("summary"), str) or not value["summary"].strip():
            raise RuntimeError("Qoder response has no summary")
        if len(value["summary"]) > 8000:
            raise RuntimeError("Qoder response summary is too long")
        citations = value.get("citations", [])
        if not isinstance(citations, list) or not all(isinstance(item, dict) for item in citations):
            raise RuntimeError("Qoder response citations are invalid")
        if allowed_ids is None:
            allowed_ids = RealQoderRuntime._authorized_ids(tool_payload)
        for citation in citations:
            key = (str(citation.get("kind") or ""), str(citation.get("id") or ""))
            if key not in allowed_ids:
                raise RuntimeError("Qoder response cites unauthorized data")
        actual_calls = [dict(item) for item in (tool_calls or [])]
        succeeded_tools = {
            str(item.get("name")) for item in actual_calls if item.get("status") == "succeeded"
        }
        required_tools: set[str] = set()
        if request_kind == "calculation_planning" and isinstance(tool_payload.get("plan"), dict):
            required_tools.add("prepare_workflow_draft")
            has_uploaded_structure = any(
                isinstance(item, dict) and item.get("category") == "structure"
                for item in tool_payload.get("files", [])
            )
            required_tools.add(
                "inspect_uploaded_structures" if has_uploaded_structure else "search_structure_library"
            )
        elif request_kind == "result_analysis":
            if any(
                isinstance(item, dict) and item.get("category") == "result"
                for item in tool_payload.get("files", [])
            ):
                required_tools.add("analyze_vasp_results")
            if isinstance(tool_payload.get("workflow"), dict):
                required_tools.add("read_workflow_summary")
        elif request_kind in {"file_analysis", "general_qa"}:
            if any(
                isinstance(item, dict) and item.get("category") == "result"
                for item in tool_payload.get("files", [])
            ):
                required_tools.add("analyze_vasp_results")
            if any(
                isinstance(item, dict) and item.get("category") == "structure"
                for item in tool_payload.get("files", [])
            ):
                required_tools.add("inspect_uploaded_structures")
            if isinstance(tool_payload.get("workflow"), dict):
                required_tools.add("read_workflow_summary")
            if any(isinstance(item, dict) for item in tool_payload.get("structures", [])):
                required_tools.add("search_structure_library")
        if not required_tools.issubset(succeeded_tools):
            raise RuntimeError("Qoder did not use the required controlled tools")
        parameter_changes = RealQoderRuntime._validated_parameter_changes(
            value.get("parameter_changes", []), tool_payload,
        )
        return {
            "provider": "qoder",
            "summary": value["summary"].strip(),
            "citations": citations,
            "tool_calls": actual_calls,
            "workspace": {},
            "parameter_changes": parameter_changes,
            "advisory_only": True,
            "prompt_length": len(raw),
        }

    @staticmethod
    def _authorized_ids(tool_payload: dict[str, object]) -> set[tuple[str, str]]:
        allowed: set[tuple[str, str]] = set()
        for collection, kind in (
            (tool_payload.get("files", []), "file"),
            (tool_payload.get("structures", []), "structure"),
            (tool_payload.get("templates", []), "template"),
            (tool_payload.get("literature", []), "literature"),
        ):
            for item in collection:
                if isinstance(item, dict) and item.get("id"):
                    allowed.add((kind, str(item["id"])))
        workflow = tool_payload.get("workflow")
        if isinstance(workflow, dict) and workflow.get("id"):
            allowed.add(("workflow", str(workflow["id"])))
        plan = tool_payload.get("plan")
        if isinstance(plan, dict):
            for collection, kind in (("structures", "structure"), ("templates", "template")):
                for item in plan.get(collection, []):
                    if isinstance(item, dict) and item.get("id"):
                        allowed.add((kind, str(item["id"])))
        return allowed

    @staticmethod
    def _validated_parameter_changes(
        raw_changes: object,
        tool_payload: dict[str, object],
    ) -> list[dict[str, str]]:
        plan = tool_payload.get("plan")
        return validated_parameter_changes(plan, raw_changes) if isinstance(plan, dict) else []
