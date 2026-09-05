from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import urllib.request
from pathlib import Path, PurePosixPath


SUCCESS_WORKFLOW_ID = "4b566547-961b-4e10-a8d0-99431f2e2229"
FAILURE_WORKFLOW_ID = "db9c793d-cf8f-4207-823b-5943d825f21d"
SUCCESS_BUNDLE_SHA256 = "a99e338c6a00fa2d1129bf9fbbe910a959f3c419955370f995da8242850ba8b4"
FAILURE_BUNDLE_SHA256 = "7addf0ede65844a211e1460d0e53fc4f88792e7928c0af2541bc791e7595ae0e"
EXPECTED_CORE_ROUTERS = (("auth", "competition_router"), ("routers.health", "router"))
EXPECTED_BUSINESS_ROUTERS = (
    ("routers.competition_workflows", "router"),
    ("routers.competition_cluster", "router"),
)
FORBIDDEN_ROUTE_PREFIXES = (
    "/api/agents",
    "/api/qe",
    "/api/epw",
    "/api/projects",
    "/api/devices",
    "/api/server-monitor",
    "/api/dailypapers",
    "/api/academic-reports",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_NODE_RE = re.compile(r"anode(0[1-9]|1[0-9]|2[0-6])")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)


def _read_regular(path: Path, maximum: int = 1024 * 1024) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"required regular file is missing: {path}")
    if path.stat().st_size > maximum:
        raise RuntimeError(f"required file is unexpectedly large: {path}")
    return path.read_bytes()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError:
        return False
    return True


def _verify_release_manifest(release: Path) -> dict:
    manifest_path = release / "manifest.txt"
    digest_path = release / "manifest.sha256"
    digest_line = _read_regular(digest_path, 256).decode("ascii").strip()
    match = re.fullmatch(r"([0-9a-f]{64})  manifest\.txt", digest_line)
    if match is None:
        raise RuntimeError("release manifest digest line is invalid")
    manifest_sha256 = _sha256(manifest_path)
    if manifest_sha256 != match.group(1):
        raise RuntimeError("release manifest digest changed")

    entries = _read_regular(manifest_path, 16 * 1024 * 1024).decode("utf-8").splitlines()
    seen: set[str] = set()
    for line in entries:
        item = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if item is None:
            raise RuntimeError("release manifest contains an invalid line")
        expected, relative = item.groups()
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or relative in seen:
            raise RuntimeError("release manifest contains an unsafe path")
        seen.add(relative)
        path = release / Path(*pure.parts)
        if path.is_symlink() or not path.is_file() or not _inside(path, release):
            raise RuntimeError(f"release manifest target is unsafe: {relative}")
        if _sha256(path) != expected:
            raise RuntimeError(f"release file digest changed: {relative}")
    if not entries:
        raise RuntimeError("release manifest is empty")
    return {"entry_count": len(entries), "manifest_sha256": manifest_sha256}


def _verify_database(database: Path) -> dict:
    if database.is_symlink() or not database.is_file():
        raise RuntimeError("competition database is missing or unsafe")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"competition database integrity failed: {integrity}")
        identifiers = {row[0] for row in connection.execute("SELECT id FROM workflow_runs")}
        required = {SUCCESS_WORKFLOW_ID, FAILURE_WORKFLOW_ID}
        if not required.issubset(identifiers):
            raise RuntimeError("fixed Stage 7 workflows are missing")
        return {"integrity_check": integrity, "workflow_count": len(identifiers)}
    finally:
        connection.close()


def _load_json_url(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"runtime probe returned HTTP {response.status}")
        return json.load(response)


def _node_to_address(node: str) -> str:
    match = _NODE_RE.fullmatch(node)
    if match is None:
        raise RuntimeError("service node is invalid")
    number = int(match.group(1))
    return f"11.11.10.{number}"


def _verify_runtime(root: Path, commit: str, manifest_sha256: str) -> dict:
    state_path = root / "runtime" / "service-state.json"
    state = json.loads(_read_regular(state_path, 4096))
    expected_values = {
        "schema": "lmatelab-107cup-service-state-v1",
        "commit": commit,
        "manifest_sha256": manifest_sha256,
    }
    for key, value in expected_values.items():
        if state.get(key) != value:
            raise RuntimeError(f"service state mismatch: {key}")
    job_id = str(state.get("job_id", ""))
    node = str(state.get("node", ""))
    port = state.get("port")
    if re.fullmatch(r"[1-9][0-9]*", job_id) is None:
        raise RuntimeError("service Job ID is invalid")
    node_address = _node_to_address(node)
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise RuntimeError("service port is invalid")

    live = _load_json_url(f"http://{node_address}:{port}/api/health/live")
    ready = _load_json_url(f"http://{node_address}:{port}/api/health/ready")
    for key, value in {
        "status": "ok",
        "job_id": job_id,
        "node": node,
        "commit": commit,
        "manifest_sha256": manifest_sha256,
        "release_kind": "stable",
        "data_mode": "live",
    }.items():
        if live.get(key) != value:
            raise RuntimeError(f"live runtime identity mismatch: {key}")
    if ready != {"status": "ready"}:
        raise RuntimeError("runtime readiness response is invalid")
    return {"job_id": job_id, "node": node, "port": port}


def _verify_route_scope() -> dict:
    from competition_runtime import BUSINESS_ROUTER_IMPORTS, CORE_ROUTER_IMPORTS
    from main_107cup import app

    if tuple(CORE_ROUTER_IMPORTS) != EXPECTED_CORE_ROUTERS:
        raise RuntimeError("107 Cup core router allowlist changed")
    if tuple(BUSINESS_ROUTER_IMPORTS) != EXPECTED_BUSINESS_ROUTERS:
        raise RuntimeError("107 Cup business router allowlist changed")
    routes = sorted({getattr(route, "path", "") for route in app.routes})
    forbidden = [
        route
        for route in routes
        if any(route.startswith(prefix) for prefix in FORBIDDEN_ROUTE_PREFIXES)
    ]
    if forbidden:
        raise RuntimeError(f"forbidden business routes entered the release: {forbidden}")
    if "/api/competition/cluster-resources" not in routes:
        raise RuntimeError("cluster resource route is missing")
    return {
        "route_count": len(routes),
        "core_routers": [list(item) for item in CORE_ROUTER_IMPORTS],
        "business_routers": [list(item) for item in BUSINESS_ROUTER_IMPORTS],
        "forbidden_routes": forbidden,
    }


def _load_stage8_harness(release: Path):
    path = release / "source" / "deploy" / "107cup" / "slurm" / "stage8-acceptance.py"
    spec = importlib.util.spec_from_file_location("lmatelab_stage8_acceptance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the Stage 8 acceptance harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "run_acceptance", None)):
        raise RuntimeError("Stage 8 acceptance harness has no reusable entry point")
    return module


def _write_evidence_manifest(output_dir: Path) -> None:
    entries = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.sha256":
            relative = path.relative_to(output_dir).as_posix()
            entries.append(f"{_sha256(path)}  {relative}")
    _write_private(output_dir / "manifest.sha256", ("\n".join(entries) + "\n").encode("ascii"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Stage 10 acceptance must run through Slurm")

    root = args.root.resolve(strict=True)
    expected_root = Path("/home/scc/pb23030683/lmatelab-107cup")
    if root != expected_root:
        raise RuntimeError("Stage 10 acceptance root is not the 107 competition root")
    current = root / "current"
    if not current.is_symlink():
        raise RuntimeError("stable current release is not a symlink")
    release = current.resolve(strict=True)
    if release.parent != root / "releases" or not re.fullmatch(r"[0-9a-f]{40}", release.name):
        raise RuntimeError("stable current release target is invalid")
    commit = _read_regular(release / "commit.txt", 64).decode("ascii").strip()
    expected_commit = os.environ.get("LMATELAB_STAGE10_EXPECTED_COMMIT", "")
    if commit != release.name or commit != expected_commit:
        raise RuntimeError("Stage 10 release is not the fixed merged main commit")

    output_dir = args.output_dir
    if not _inside(output_dir.parent, root / "evidence"):
        raise RuntimeError("Stage 10 evidence directory is outside the competition root")
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)

    release_audit = _verify_release_manifest(release)
    database = (root / "data" / "db" / "eln.db").resolve(strict=True)
    workflow_directory = (root / "data" / "workflows").resolve(strict=True)
    for path in (database, workflow_directory, release, output_dir):
        if not _inside(path, root):
            raise RuntimeError(f"business path escaped the 107 competition root: {path}")
    database_audit = _verify_database(database)
    runtime_audit = _verify_runtime(root, commit, release_audit["manifest_sha256"])
    route_audit = _verify_route_scope()

    stage8_dir = output_dir / "stage8-read-only"
    stage8 = _load_stage8_harness(release).run_acceptance(stage8_dir)
    if stage8.get("success_bundle_sha256") != SUCCESS_BUNDLE_SHA256:
        raise RuntimeError("fixed success evidence bundle changed")
    if stage8.get("failure_bundle_sha256") != FAILURE_BUNDLE_SHA256:
        raise RuntimeError("fixed failure evidence bundle changed")

    summary = {
        "schema": "lmatelab-107cup-stage10-acceptance-v1",
        "status": "machine_gates_passed",
        "slurm_job_id": os.environ["SLURM_JOB_ID"],
        "acceptance_node": os.environ.get("SLURMD_NODENAME", os.environ.get("HOSTNAME")),
        "release_commit": commit,
        "release": release_audit,
        "service": runtime_audit,
        "database": database_audit,
        "route_scope": route_audit,
        "data_locations": {
            "release": str(release),
            "python_environment": str(root / "envs" / "python"),
            "database": str(database),
            "workflows": str(workflow_directory),
            "evidence": str(output_dir),
        },
        "success_workflow": SUCCESS_WORKFLOW_ID,
        "failure_workflow": FAILURE_WORKFLOW_ID,
        "success_bundle_sha256": stage8["success_bundle_sha256"],
        "failure_bundle_sha256": stage8["failure_bundle_sha256"],
        "external_gates": ["fresh_operator_browser", "fresh_viewer_browser", "three_member_review"],
    }
    _write_private(
        output_dir / "summary.json",
        (json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"),
    )
    _write_evidence_manifest(output_dir)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    print("STAGE10_ACCEPTANCE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
