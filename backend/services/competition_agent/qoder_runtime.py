from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


DISABLED_BUILTIN_TOOLS = ("Bash", "Write", "Edit", "Read", "Glob", "WebFetch")


@dataclass(frozen=True)
class QoderRuntimeConfig:
    permission_mode: str = "dont_ask"
    yolo: bool = False
    allowed_builtin_tools: tuple[str, ...] = ()
    disabled_builtin_tools: tuple[str, ...] = DISABLED_BUILTIN_TOOLS

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None):
        _ = environ
        return cls()


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
        else:
            workflow = tool_payload.get("workflow")
            workflow_id = workflow.get("id") if isinstance(workflow, dict) else None
            status = workflow.get("status") if isinstance(workflow, dict) else "unknown"
            summary = (
                f"工作流 {workflow_id} 的权威记录状态为 {status}。"
                "本分析只解释持久化证据，不替代科学验收。"
            )
            citations = [{"kind": "workflow", "id": workflow_id}]
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

    def run(self, **_kwargs) -> dict[str, object]:
        if self._environ.get("LMATELAB_QODER_REAL_NETWORK_AUTHORIZED") != "1":
            raise RuntimeError("real Qoder runtime is not authorized")
        if not self._environ.get("QODER_PERSONAL_ACCESS_TOKEN"):
            raise RuntimeError("Qoder personal access token is unavailable")
        try:
            __import__("qoder_agent_sdk")
        except ImportError as exc:
            raise RuntimeError("qoder-agent-sdk is not installed") from exc
        raise RuntimeError("real Qoder runtime preflight requires explicit implementation approval")
