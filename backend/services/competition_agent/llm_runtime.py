from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import httpx

from services.competition_agent.settings import read_settings


def llm_configured(environ: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environ is None else environ
    if values.get("LMATELAB_LLM_API_KEY", "").strip():
        return True
    key_file = values.get("LMATELAB_LLM_API_KEY_FILE", "").strip()
    if not key_file:
        return False
    try:
        path = Path(key_file)
        return path.is_file() and path.stat().st_mode & 0o077 == 0 and path.stat().st_size > 0
    except OSError:
        return False


@dataclass(frozen=True)
class LLMRuntimeConfig:
    api_url: str
    model: str
    api_key: str
    timeout_seconds: float = 120.0

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None):
        values = os.environ if environ is None else environ
        saved = read_settings(values)
        api_url = saved["api_url"].strip()
        model = saved["model"].strip()
        api_key = values.get("LMATELAB_LLM_API_KEY", "").strip()
        key_file = values.get("LMATELAB_LLM_API_KEY_FILE", "").strip()
        if not api_key and key_file:
            path = Path(key_file)
            if path.stat().st_mode & 0o077:
                raise RuntimeError("LLM API key file must have mode 0600")
            api_key = path.read_text(encoding="utf-8").strip()
        if not api_url.startswith("https://"):
            raise RuntimeError("LLM API URL must use HTTPS")
        if not model:
            raise RuntimeError("LLM model is unavailable")
        if not api_key:
            raise RuntimeError("LLM API key is unavailable")
        return cls(
            api_url=api_url,
            model=model,
            api_key=api_key,
            timeout_seconds=float(values.get("LMATELAB_LLM_TIMEOUT_SECONDS", "120")),
        )


class OpenAICompatibleRuntime:
    provider = "llm"

    def __init__(self, environ: Mapping[str, str] | None = None, client=None):
        self.config = LLMRuntimeConfig.from_environ(environ)
        self._client = client

    def run(
        self,
        *,
        request_kind: str,
        prompt: str,
        tool_payload: dict[str, object],
    ) -> dict[str, object]:
        authorized_ids = self._authorized_ids(tool_payload)
        system_prompt = (
            "You are LMateLab's scientific assistant. Analyze only the supplied authorized "
            "context. You may recommend a calculation plan, but do not claim that a calculation "
            "has run or that a file has changed. A user must review and submit every workflow. Return "
            "one JSON object with keys summary, citations, tool_calls, workspace, "
            "parameter_changes, and "
            "advisory_only. citations must be an array of objects whose kind and id exactly "
            "match supplied sources. tool_calls must be [] and advisory_only must be true."
            " For calculation_planning, parameter_changes may contain template_id, parameter, "
            "value, and reason, but only use each template's editable_parameters. Never change "
            "fixed parameters or invent a template."
        )
        request = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "request_kind": request_kind,
                            "question": prompt,
                            "authorized_context": tool_payload,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        }
        client = self._client or httpx.Client(timeout=self.config.timeout_seconds)
        close_client = self._client is None
        try:
            response = client.post(
                self.config.api_url,
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                json=request,
            )
            response.raise_for_status()
            body = response.json()
        finally:
            if close_client:
                client.close()
        try:
            message = body["choices"][0]["message"]
            raw = message.get("content") or message.get("reasoning_content")
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM response has no assistant content") from exc
        return self._validated_output(raw, authorized_ids, tool_payload)

    @staticmethod
    def _authorized_ids(tool_payload: dict[str, object]) -> set[tuple[str, str]]:
        allowed: set[tuple[str, str]] = set()
        for item in tool_payload.get("files", []):
            if isinstance(item, dict) and item.get("id"):
                allowed.add(("file", str(item["id"])))
        workflow = tool_payload.get("workflow")
        if isinstance(workflow, dict) and workflow.get("id"):
            allowed.add(("workflow", str(workflow["id"])))
        for item in tool_payload.get("templates", []):
            if isinstance(item, dict) and item.get("id"):
                allowed.add(("template", str(item["id"])))
        for item in tool_payload.get("structures", []):
            if isinstance(item, dict) and item.get("id"):
                allowed.add(("structure", str(item["id"])))
        for item in tool_payload.get("literature", []):
            if isinstance(item, dict) and item.get("id"):
                allowed.add(("literature", str(item["id"])))
        plan = tool_payload.get("plan")
        if isinstance(plan, dict):
            for collection, kind in (("structures", "structure"), ("templates", "template")):
                for item in plan.get(collection, []):
                    if isinstance(item, dict) and item.get("id"):
                        allowed.add((kind, str(item["id"])))
        return allowed

    @staticmethod
    def _validated_output(
        raw: object,
        allowed: set[tuple[str, str]],
        tool_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if not isinstance(raw, str):
            raise RuntimeError("LLM returned invalid content")
        candidate = raw.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL)
        if fenced:
            candidate = fenced.group(1)
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            value = {"summary": candidate}
        summary = value.get("summary") if isinstance(value, dict) else None
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 16000:
            raise RuntimeError("LLM response summary is invalid")
        citations = [{"kind": kind, "id": identifier} for kind, identifier in sorted(allowed)]
        editable: dict[str, set[str]] = {}
        plan = (tool_payload or {}).get("plan")
        if isinstance(plan, dict):
            for template in plan.get("templates", []):
                if isinstance(template, dict) and template.get("id"):
                    editable[str(template["id"])] = {
                        str(item).upper() for item in template.get("editable_parameters", [])
                    }
        parameter_changes = []
        raw_changes = value.get("parameter_changes", []) if isinstance(value, dict) else []
        if isinstance(raw_changes, list):
            for item in raw_changes[:24]:
                if not isinstance(item, dict):
                    continue
                template_id = str(item.get("template_id") or "")
                parameter = str(item.get("parameter") or "").upper()
                candidate_value = str(item.get("value") or "").strip()
                reason = str(item.get("reason") or "").strip()
                if (
                    parameter in editable.get(template_id, set())
                    and candidate_value
                    and len(candidate_value) <= 120
                    and not any(char in candidate_value for char in "\r\n;`$")
                ):
                    parameter_changes.append({
                        "template_id": template_id,
                        "parameter": parameter,
                        "value": candidate_value,
                        "reason": reason[:500],
                    })
        return {
            "provider": "llm",
            "summary": summary.strip(),
            "citations": citations,
            "tool_calls": [],
            "workspace": {},
            "parameter_changes": parameter_changes,
            "advisory_only": True,
            "prompt_length": len(raw),
        }
