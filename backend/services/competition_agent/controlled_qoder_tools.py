from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from services.competition_agent.planning import uploaded_structure
from services.competition_agent.structure_library import search_structures
from services.competition_agent.vasp_analysis import analyze_vasp_files


CONTROLLED_QODER_TOOL_NAMES = (
    "search_structure_library",
    "inspect_uploaded_structures",
    "analyze_vasp_results",
    "read_workflow_summary",
    "prepare_workflow_draft",
)
MAX_CONTROLLED_TOOL_CALLS = 8
MCP_SERVER_NAME = "lmatelab"


class ControlledQoderToolError(ValueError):
    pass


def _clone(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _bounded_ids(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > 12:
        raise ControlledQoderToolError("file_ids must be a list with at most 12 entries")
    if any(not isinstance(item, str) or not item or len(item) > 160 for item in value):
        raise ControlledQoderToolError("file_ids contain an invalid identifier")
    return list(dict.fromkeys(value))


class ControlledQoderToolSession:
    """Owner-scoped, read-only data facade for one Qoder request."""

    def __init__(
        self,
        tool_payload: dict[str, object],
        *,
        max_calls: int = MAX_CONTROLLED_TOOL_CALLS,
        structure_search: Callable[[str, int], dict[str, object]] = search_structures,
    ):
        if not 1 <= max_calls <= MAX_CONTROLLED_TOOL_CALLS:
            raise ValueError("controlled Qoder call budget is invalid")
        self._payload = tool_payload
        self._max_calls = max_calls
        self._structure_search = structure_search
        self.calls: list[dict[str, object]] = []
        self.exposed_ids: set[tuple[str, str]] = set()

    def context_index(self) -> dict[str, object]:
        files = [
            {
                key: item.get(key)
                for key in ("id", "name", "category", "calculation_id", "group_name")
                if item.get(key) is not None
            }
            for item in self._payload.get("files", [])
            if isinstance(item, dict)
        ]
        workflow = self._payload.get("workflow")
        workflow_index = None
        if isinstance(workflow, dict) and workflow.get("id"):
            workflow_index = {"id": workflow["id"]}
        plan = self._payload.get("plan")
        plan_index = None
        if isinstance(plan, dict):
            plan_index = {
                "material_formula": plan.get("material_formula"),
                "needs_upload": plan.get("needs_upload") is True,
                "steps": list(plan.get("steps", []))[:4],
                "structure_ids": [
                    str(item["id"])
                    for item in plan.get("structures", [])[:10]
                    if isinstance(item, dict) and item.get("id")
                ],
                "template_ids": [
                    str(item["id"])
                    for item in plan.get("templates", [])[:4]
                    if isinstance(item, dict) and item.get("id")
                ],
            }
        literature = [
            {key: item.get(key) for key in ("id", "title", "year") if item.get(key) is not None}
            for item in self._payload.get("literature", [])
            if isinstance(item, dict)
        ]
        return {
            "available_tools": list(CONTROLLED_QODER_TOOL_NAMES),
            "files": files,
            "selected_structures": [
                {
                    key: item.get(key)
                    for key in ("id", "formula", "source")
                    if item.get(key) is not None
                }
                for item in self._payload.get("structures", [])
                if isinstance(item, dict)
            ],
            "workflow": workflow_index,
            "plan": plan_index,
            "literature": literature,
            "conversation_history": _clone(self._payload.get("conversation_history", [])),
        }

    def invoke(self, name: str, arguments: object) -> dict[str, object]:
        if name not in CONTROLLED_QODER_TOOL_NAMES:
            raise ControlledQoderToolError("tool is not allowed")
        if len(self.calls) >= self._max_calls:
            raise ControlledQoderToolError("controlled Qoder tool call limit reached")
        if not isinstance(arguments, dict):
            raise ControlledQoderToolError("tool arguments must be an object")
        call = {"name": name, "status": "running"}
        self.calls.append(call)
        try:
            result = getattr(self, f"_{name}")(arguments)
        except ControlledQoderToolError:
            call["status"] = "failed"
            raise
        call["status"] = "succeeded"
        self._collect_exposed_ids(name, result)
        return result

    def _search_structure_library(self, arguments: dict[str, object]) -> dict[str, object]:
        if set(arguments) - {"query", "limit"}:
            raise ControlledQoderToolError("structure search arguments are invalid")
        query = arguments.get("query", "")
        limit = arguments.get("limit", 10)
        if not isinstance(query, str) or len(query) > 100 or "\x00" in query:
            raise ControlledQoderToolError("structure search query is invalid")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ControlledQoderToolError("structure search limit is invalid")
        result = self._structure_search(query.strip(), limit)
        return {
            "items": _clone(list(result.get("items", []))[:limit]),
            "total": int(result.get("total", 0)),
            "sources": _clone(result.get("sources", [])),
        }

    def _inspect_uploaded_structures(self, arguments: dict[str, object]) -> dict[str, object]:
        if set(arguments) != {"file_ids"}:
            raise ControlledQoderToolError("uploaded structure arguments are invalid")
        requested = _bounded_ids(arguments["file_ids"])
        authorized = {
            str(item.get("id")): item
            for item in self._payload.get("files", [])
            if isinstance(item, dict) and item.get("category") == "structure" and item.get("id")
        }
        if any(item not in authorized for item in requested):
            raise ControlledQoderToolError("one or more structure files are not authorized")
        items = []
        for identifier in requested:
            parsed = uploaded_structure(authorized[identifier])
            if parsed is None:
                items.append({"file_id": identifier, "parse_warning": "structure could not be parsed"})
                continue
            _item, workspace = parsed
            items.append({
                "file_id": identifier,
                "name": authorized[identifier].get("name"),
                "source": "user-upload",
                "workflow_compatible": workspace["workflow_compatible"],
                "summary": _clone(workspace["summary"]),
            })
        return {"items": items}

    def _analyze_vasp_results(self, arguments: dict[str, object]) -> dict[str, object]:
        if set(arguments) != {"file_ids"}:
            raise ControlledQoderToolError("VASP analysis arguments are invalid")
        requested = _bounded_ids(arguments["file_ids"])
        authorized = {
            str(item.get("id")): item
            for item in self._payload.get("files", [])
            if isinstance(item, dict) and item.get("category") == "result" and item.get("id")
        }
        if any(item not in authorized for item in requested):
            raise ControlledQoderToolError("one or more result files are not authorized")
        return {"items": analyze_vasp_files([authorized[item] for item in requested])}

    def _read_workflow_summary(self, arguments: dict[str, object]) -> dict[str, object]:
        if set(arguments) != {"workflow_id"}:
            raise ControlledQoderToolError("workflow summary arguments are invalid")
        workflow_id = arguments.get("workflow_id")
        workflow = self._payload.get("workflow")
        if (
            not isinstance(workflow_id, str)
            or not isinstance(workflow, dict)
            or str(workflow.get("id")) != workflow_id
        ):
            raise ControlledQoderToolError("workflow is not authorized")
        return _clone(workflow)

    def _prepare_workflow_draft(self, arguments: dict[str, object]) -> dict[str, object]:
        if arguments:
            raise ControlledQoderToolError("workflow draft accepts no arguments")
        plan = self._payload.get("plan")
        if not isinstance(plan, dict):
            raise ControlledQoderToolError("workflow draft is unavailable")
        return {
            "material_formula": plan.get("material_formula"),
            "needs_upload": plan.get("needs_upload") is True,
            "reason": plan.get("reason"),
            "steps": _clone(list(plan.get("steps", []))[:4]),
            "structures": _clone(list(plan.get("structures", []))[:10]),
            "templates": [
                {
                    key: item.get(key)
                    for key in (
                        "id", "step", "filename", "rendered_content", "editable_parameters"
                    )
                }
                for item in plan.get("templates", [])[:4]
                if isinstance(item, dict)
            ],
        }

    def _collect_exposed_ids(self, name: str, result: dict[str, object]) -> None:
        if name == "search_structure_library":
            for item in result.get("items", []):
                if isinstance(item, dict) and item.get("id"):
                    self.exposed_ids.add(("structure", str(item["id"])))
        elif name == "inspect_uploaded_structures":
            for item in result.get("items", []):
                if isinstance(item, dict) and item.get("file_id"):
                    self.exposed_ids.add(("file", str(item["file_id"])))
        elif name == "analyze_vasp_results":
            for item in result.get("items", []):
                if isinstance(item, dict) and item.get("file_id"):
                    self.exposed_ids.add(("file", str(item["file_id"])))
        elif name == "read_workflow_summary" and result.get("id"):
            self.exposed_ids.add(("workflow", str(result["id"])))
        elif name == "prepare_workflow_draft":
            for collection, kind in (("structures", "structure"), ("templates", "template")):
                for item in result.get(collection, []):
                    if isinstance(item, dict) and item.get("id"):
                        self.exposed_ids.add((kind, str(item["id"])))


def build_sdk_mcp_server(session: ControlledQoderToolSession, sdk_module):
    annotations = sdk_module.ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    schemas = {
        "search_structure_library": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": 100},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "additionalProperties": False,
        },
        "inspect_uploaded_structures": {
            "type": "object",
            "properties": {"file_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 12}},
            "required": ["file_ids"],
            "additionalProperties": False,
        },
        "analyze_vasp_results": {
            "type": "object",
            "properties": {"file_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 12}},
            "required": ["file_ids"],
            "additionalProperties": False,
        },
        "read_workflow_summary": {
            "type": "object",
            "properties": {"workflow_id": {"type": "string"}},
            "required": ["workflow_id"],
            "additionalProperties": False,
        },
        "prepare_workflow_draft": {
            "type": "object", "properties": {}, "additionalProperties": False,
        },
    }
    descriptions = {
        "search_structure_library": "Search the read-only LMateLab QMOF and curated structure index.",
        "inspect_uploaded_structures": "Inspect only structure files mounted by the current user request.",
        "analyze_vasp_results": "Run fixed read-only parsers on mounted VASP result files.",
        "read_workflow_summary": "Read the sanitized summary of the mounted LMateLab workflow.",
        "prepare_workflow_draft": "Read the deterministic LMateLab calculation draft and editable parameter boundary.",
    }

    def registered(name: str):
        async def handler(arguments):
            try:
                result = session.invoke(name, arguments)
                return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
            except ControlledQoderToolError as exc:
                return {
                    "content": [{"type": "text", "text": str(exc)}],
                    "is_error": True,
                }

        return sdk_module.tool(
            name,
            descriptions[name],
            schemas[name],
            annotations=annotations,
        )(handler)

    tools = [registered(name) for name in CONTROLLED_QODER_TOOL_NAMES]
    return sdk_module.create_sdk_mcp_server(MCP_SERVER_NAME, version="1.0.0", tools=tools)
