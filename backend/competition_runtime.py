from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping


CORE_ROUTER_IMPORTS = (
    ("auth", "competition_router"),
    ("routers.health", "router"),
)

BUSINESS_ROUTER_IMPORTS = (
    ("routers.competition_workflows", "router"),
)

SQLITE_CONNECTION_PRAGMAS = (
    "PRAGMA foreign_keys=ON;",
    "PRAGMA journal_mode=DELETE;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA busy_timeout=5000;",
)


def workflow_root(environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    return Path(
        values.get(
            "LMATELAB_WORKFLOW_ROOT",
            "/home/scc/pb23030683/lmatelab-107cup/data/workflows",
        )
    )


def release_commit(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    commit = values.get("LMATELAB_GIT_COMMIT", "")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("LMATELAB_GIT_COMMIT must be a full lowercase Git SHA")
    return commit


def deployment_metadata(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if environ is None else environ
    return {
        "job_id": values.get("SLURM_JOB_ID", "unknown"),
        "node": values.get("SLURMD_NODENAME", values.get("HOSTNAME", "unknown")),
        "commit": values.get("LMATELAB_GIT_COMMIT", "unknown"),
        "manifest_sha256": values.get("LMATELAB_MANIFEST_SHA256", "unknown"),
        "started_at": values.get("LMATELAB_STARTED_AT", "unknown"),
        "release_kind": values.get("LMATELAB_RELEASE_KIND", "stable"),
        "data_mode": values.get("LMATELAB_DATA_MODE", "live"),
    }


def resolve_frontend_file(frontend_root: Path | str, request_path: str) -> Path:
    root = Path(frontend_root).resolve()
    normalized = (request_path or "").lstrip("/")

    if normalized == "api" or normalized.startswith("api/"):
        raise LookupError("API requests must not use the SPA fallback")

    candidate = (root / normalized).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("frontend path escapes the configured root")

    if candidate.is_file():
        return candidate

    index = root / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"frontend index is missing: {index}")
    return index
