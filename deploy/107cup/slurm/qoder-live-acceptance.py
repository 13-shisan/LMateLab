from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from services.competition_agent.controlled_qoder_tools import CONTROLLED_QODER_TOOL_NAMES
from services.competition_agent.planning import calculation_plan
from services.competition_agent.qoder_runtime import RealQoderRuntime


PROMPT = (
    "Plan a standard PBE relax, SCF, band and DOS workflow for MoS2. "
    "You must call search_structure_library and prepare_workflow_draft. "
    "Do not execute, submit, cancel, or modify anything."
)
REQUIRED_TOOLS = {"search_structure_library", "prepare_workflow_draft"}
EXPECTED_STEPS = ["relax", "scf", "band", "dos"]


def _agent_database_snapshot(path: Path) -> dict[str, object]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        count = connection.execute("SELECT COUNT(*) FROM competition_agent_runs").fetchone()[0]
        latest = connection.execute(
            "SELECT COALESCE(MAX(updated_at), '') FROM competition_agent_runs"
        ).fetchone()[0]
    return {"count": int(count), "latest_updated_at": str(latest)}


def _fail(message: str) -> int:
    print(json.dumps({"status": "failed", "reason": message}, sort_keys=True))
    return 1


def _runtime_error_code(exc: Exception) -> str:
    message = str(exc).casefold()
    if "credit" in message or "quota" in message:
        return "qoder-credit-unavailable"
    if "auth" in message or "login" in message or "token" in message:
        return "qoder-authentication-failed"
    if "timeout" in message or "timed out" in message:
        return "qoder-request-timeout"
    if "required controlled tools" in message:
        return "required-tools-missing"
    if "invalid json" in message:
        return "invalid-advisory-response"
    return f"qoder-runtime-{type(exc).__name__.casefold()}"


def main() -> int:
    if not os.environ.get("SLURM_JOB_ID"):
        return _fail("acceptance must run through Slurm")
    if os.environ.get("LMATELAB_QODER_REAL_NETWORK_AUTHORIZED") != "1":
        return _fail("isolated Qoder network authorization is disabled")

    database = Path(
        os.environ.get(
            "LMATELAB_PRIMARY_DATABASE",
            "/home/scc/pb23030683/lmatelab-107cup/data/db/eln.db",
        )
    ).resolve(strict=True)
    before = _agent_database_snapshot(database)
    plan = calculation_plan(PROMPT, [], [])
    if plan.get("steps") != EXPECTED_STEPS:
        return _fail("deterministic workflow plan is incomplete")
    if plan.get("needs_upload") is True or not plan.get("structures"):
        return _fail("read-only structure source is unavailable")

    try:
        result = RealQoderRuntime().run(
            request_kind="calculation_planning",
            prompt=PROMPT,
            tool_payload={"files": [], "plan": plan},
        )
    except Exception as exc:
        return _fail(_runtime_error_code(exc))

    after = _agent_database_snapshot(database)
    calls = result.get("tool_calls", [])
    succeeded = {
        str(item.get("name"))
        for item in calls
        if isinstance(item, dict) and item.get("status") == "succeeded"
    }
    call_names = [
        str(item.get("name")) for item in calls if isinstance(item, dict)
    ]
    checks = {
        "provider_is_qoder": result.get("provider") == "qoder",
        "advisory_only": result.get("advisory_only") is True,
        "required_tools_succeeded": REQUIRED_TOOLS.issubset(succeeded),
        "only_controlled_tools_called": set(call_names).issubset(CONTROLLED_QODER_TOOL_NAMES),
        "agent_database_unchanged": before == after,
        "complete_four_step_plan": plan.get("steps") == EXPECTED_STEPS,
    }
    if not all(checks.values()):
        return _fail("one or more controlled-runtime checks failed: " + json.dumps(checks))

    summary = str(result["summary"])
    sanitized = {
        "status": "passed",
        "slurm_job_id": os.environ["SLURM_JOB_ID"],
        "node": os.environ.get("SLURMD_NODENAME", "unknown"),
        "provider": result["provider"],
        "advisory_only": result["advisory_only"],
        "plan_steps": plan["steps"],
        "tool_calls": calls,
        "citations": [
            {"kind": item.get("kind"), "id": item.get("id")}
            for item in result.get("citations", [])
            if isinstance(item, dict)
        ],
        "parameter_change_count": len(result.get("parameter_changes", [])),
        "summary_length": len(summary),
        "summary_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
        "checks": checks,
    }
    print(json.dumps(sanitized, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
