from __future__ import annotations

import os
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


DISABLED_BUILTIN_TOOLS = ("Bash", "Write", "Edit", "Read", "Glob", "WebFetch")


@dataclass(frozen=True)
class QoderRuntimeConfig:
    permission_mode: str = "dontAsk"
    yolo: bool = False
    allowed_builtin_tools: tuple[str, ...] = ()
    disabled_builtin_tools: tuple[str, ...] = DISABLED_BUILTIN_TOOLS
    model: str | None = None
    auth_mode: str = "pat"
    max_turns: int = 1
    timeout_seconds: float = 120.0

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None):
        values = os.environ if environ is None else environ
        return cls(
            model=values.get("LMATELAB_QODER_MODEL") or None,
            auth_mode=values.get("LMATELAB_QODER_AUTH_MODE", "pat"),
            max_turns=int(values.get("LMATELAB_QODER_MAX_TURNS", "1")),
            timeout_seconds=float(values.get("LMATELAB_QODER_TIMEOUT_SECONDS", "120")),
        )


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
            from qodercn_agent_sdk import (
                AssistantMessage,
                QoderAgentOptions,
                ResultMessage,
                TextBlock,
                access_token_from_env,
                qodercli_auth,
                query,
            )
        except ImportError as exc:
            raise RuntimeError("qodercn-agent-sdk is not installed") from exc

        system_prompt = (
            "You are LMateLab's advisory-only VASP assistant. Use only the JSON data "
            "included in the user message. Never request or use shell, filesystem, web, "
            "network, scheduler, VASP execution, workflow mutation, or cancellation tools. "
            "Return exactly one JSON object with keys summary, citations, tool_calls, "
            "workspace, and advisory_only. advisory_only must be true. citations may only "
            "refer to template or workflow identifiers present in the supplied data. "
            "tool_calls must be an empty array because this runtime exposes no tools."
        )
        request_payload = {
            "request_kind": request_kind,
            "user_prompt": prompt,
            "authorized_data": tool_payload,
        }

        async def invoke() -> str:
            options = QoderAgentOptions(
                auth=(
                    qodercli_auth()
                    if self.config.auth_mode == "cli"
                    else access_token_from_env()
                ),
                system_prompt=system_prompt,
                tools=[],
                allowed_tools=[],
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
                async for message in query(
                    prompt=json.dumps(request_payload, ensure_ascii=False),
                    options=options,
                ):
                    if isinstance(message, AssistantMessage):
                        text_parts.extend(
                            block.text for block in message.content if isinstance(block, TextBlock)
                        )
                    elif isinstance(message, ResultMessage):
                        if message.is_error:
                            raise RuntimeError("Qoder returned an error result")
                        result_text = message.result
            return result_text or "".join(text_parts)

        raw = anyio.run(invoke)
        return self._validated_output(raw, request_kind, tool_payload)

    @staticmethod
    def _validated_output(
        raw: str,
        request_kind: str,
        tool_payload: dict[str, object],
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
        allowed_ids: set[str] = set()
        allowed_kinds: set[str]
        if request_kind == "template_recommendation":
            allowed_kinds = {"template"}
            allowed_ids.update(
                str(item["id"])
                for item in tool_payload.get("templates", [])
                if isinstance(item, dict) and item.get("id")
            )
        else:
            allowed_kinds = {"workflow"}
            workflow = tool_payload.get("workflow")
            if isinstance(workflow, dict) and workflow.get("id"):
                allowed_ids.add(str(workflow["id"]))
        for citation in citations:
            if citation.get("kind") not in allowed_kinds or str(citation.get("id")) not in allowed_ids:
                raise RuntimeError("Qoder response cites unauthorized data")
        if value.get("tool_calls") not in (None, []):
            raise RuntimeError("Qoder response contains forbidden tool calls")
        structure = tool_payload.get("structure")
        workspace = {"structure": structure} if isinstance(structure, dict) else {}
        return {
            "provider": "qoder",
            "summary": value["summary"].strip(),
            "citations": citations,
            "tool_calls": [],
            "workspace": workspace,
            "advisory_only": True,
            "prompt_length": len(raw),
        }
