from __future__ import annotations

import copy
import json
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Callable


_SCONTROL_COMMAND = (
    "/usr/bin/scontrol",
    "--json",
    "show",
    "nodes",
    "anode[01-26]",
)
_PARTITION_SPECS = (
    {
        "name": "P107-RTX5090",
        "nodes": tuple(f"anode{number:02d}" for number in range(1, 16)),
        "gpu_type": "RTX5090",
        "gpu_model": "RTX 5090",
    },
    {
        "name": "P107-A100",
        "nodes": tuple(f"anode{number:02d}" for number in range(16, 27)),
        "gpu_type": "A100",
        "gpu_model": "A100",
    },
)
_NODE_SPECS = {
    node_name: spec
    for spec in _PARTITION_SPECS
    for node_name in spec["nodes"]
}
_GPU_ENTRY_RE = re.compile(
    r"(?:^|,)gpu:(?P<type>[A-Za-z0-9_.-]+):(?P<count>[0-9]+)"
    r"(?:\([^)]*\))?(?=,|$)"
)
_STATE_RE = re.compile(r"[A-Z][A-Z0-9_]*")
_BLOCKED_STATES = frozenset(
    {
        "DOWN",
        "DRAIN",
        "DRAINED",
        "ERROR",
        "FAIL",
        "FAILING",
        "FUTURE",
        "INVALID",
        "MAINTENANCE",
        "NO_RESPOND",
        "NOT_RESPONDING",
        "POWERED_DOWN",
        "POWERING_DOWN",
        "REBOOT_REQUESTED",
        "UNKNOWN",
    }
)
_SCHEDULABLE_STATES = frozenset({"IDLE", "MIXED"})


class ClusterResourceError(RuntimeError):
    pass


def _byte_length(value: bytes | str | None) -> int:
    if value is None:
        return 0
    if isinstance(value, bytes):
        return len(value)
    return len(str(value).encode("utf-8", errors="replace"))


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    return str(value)


def _nonnegative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ClusterResourceError(f"invalid {field}")
    return value


def _wrapped_integer(value: object, field: str) -> int:
    if not isinstance(value, dict) or value.get("set") is not True:
        raise ClusterResourceError(f"invalid {field}")
    return _nonnegative_integer(value.get("number"), field)


def _parse_states(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or _STATE_RE.fullmatch(item) is None for item in value)
    ):
        raise ClusterResourceError("invalid node state")
    return tuple(value)


def _gpu_counts(
    configured: object,
    used: object,
    expected_type: str,
) -> dict[str, int | bool | None]:
    unavailable = {
        "total": None,
        "allocated": None,
        "free": None,
        "available": False,
    }
    if not isinstance(configured, str) or not configured:
        return unavailable
    if not isinstance(used, str):
        return unavailable

    configured_entries = [
        match
        for match in _GPU_ENTRY_RE.finditer(configured)
        if match.group("type") == expected_type
    ]
    if len(configured_entries) != 1:
        return unavailable
    total = int(configured_entries[0].group("count"))

    if used == "":
        allocated = 0
    else:
        used_entries = [
            match
            for match in _GPU_ENTRY_RE.finditer(used)
            if match.group("type") == expected_type
        ]
        if len(used_entries) != 1:
            return unavailable
        allocated = int(used_entries[0].group("count"))
    if allocated > total:
        raise ClusterResourceError("invalid GPU allocation")
    return {
        "total": total,
        "allocated": allocated,
        "free": total - allocated,
        "available": True,
    }


def _node_availability(
    states: tuple[str, ...],
    cpu_free: int,
    gpu: dict[str, int | bool | None],
) -> str:
    state_set = frozenset(states)
    if state_set & _BLOCKED_STATES:
        return "unavailable"
    if not gpu["available"]:
        return "unknown"
    if state_set & _SCHEDULABLE_STATES and cpu_free > 0 and int(gpu["free"]) > 0:
        return "available"
    return "busy"


def _parse_node(value: object) -> dict:
    if not isinstance(value, dict):
        raise ClusterResourceError("invalid node record")
    name = value.get("name")
    if not isinstance(name, str) or name not in _NODE_SPECS:
        raise ClusterResourceError("node is outside the allowlist")
    spec = _NODE_SPECS[name]
    partitions = value.get("partitions")
    if (
        not isinstance(partitions, list)
        or any(not isinstance(item, str) for item in partitions)
        or spec["name"] not in partitions
    ):
        raise ClusterResourceError("node partition does not match the allowlist")

    states = _parse_states(value.get("state"))
    cpu_total = _nonnegative_integer(value.get("cpus"), "cpus")
    cpu_allocated = _nonnegative_integer(value.get("alloc_cpus"), "alloc_cpus")
    cpu_free = _nonnegative_integer(value.get("alloc_idle_cpus"), "alloc_idle_cpus")
    if cpu_total < 1 or cpu_allocated > cpu_total or cpu_free > cpu_total:
        raise ClusterResourceError("invalid CPU allocation")

    memory_total = _nonnegative_integer(value.get("real_memory"), "real_memory")
    memory_allocated = _nonnegative_integer(value.get("alloc_memory"), "alloc_memory")
    memory_free = _wrapped_integer(value.get("free_mem"), "free_mem")
    if memory_total < 1 or memory_allocated > memory_total or memory_free > memory_total:
        raise ClusterResourceError("invalid memory allocation")

    gpu = _gpu_counts(value.get("gres"), value.get("gres_used"), spec["gpu_type"])
    return {
        "name": name,
        "partition": spec["name"],
        "gpu_model": spec["gpu_model"],
        "state": states[0].lower(),
        "states": [state.lower() for state in states],
        "availability": _node_availability(states, cpu_free, gpu),
        "cpu": {
            "total": cpu_total,
            "allocated": cpu_allocated,
            "free": cpu_free,
        },
        "memory_mib": {
            "total": memory_total,
            "allocated": memory_allocated,
            "free": memory_free,
        },
        "gpu": gpu,
    }


def _sum_resource(nodes: list[dict], field: str) -> dict[str, int]:
    return {
        key: sum(int(node[field][key]) for node in nodes)
        for key in ("total", "allocated", "free")
    }


def _sum_gpu(nodes: list[dict]) -> dict[str, int | bool | None]:
    if not all(node["gpu"]["available"] for node in nodes):
        return {
            "total": None,
            "allocated": None,
            "free": None,
            "available": False,
        }
    return {
        "total": sum(int(node["gpu"]["total"]) for node in nodes),
        "allocated": sum(int(node["gpu"]["allocated"]) for node in nodes),
        "free": sum(int(node["gpu"]["free"]) for node in nodes),
        "available": True,
    }


def _scheduler_timestamp(value: object) -> str:
    seconds = _wrapped_integer(value, "last_update")
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError) as exc:
        raise ClusterResourceError("invalid last_update") from exc


def parse_cluster_resources(payload: object, collected_at: datetime) -> dict:
    if not isinstance(payload, dict):
        raise ClusterResourceError("invalid scheduler payload")
    if payload.get("errors") != [] or payload.get("warnings") != []:
        raise ClusterResourceError("scheduler returned incomplete data")
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        raise ClusterResourceError("invalid node collection")

    allowed_records = [
        value
        for value in raw_nodes
        if isinstance(value, dict) and value.get("name") in _NODE_SPECS
    ]
    if len(allowed_records) != len(_NODE_SPECS):
        raise ClusterResourceError("scheduler did not return the complete node allowlist")
    nodes = [_parse_node(value) for value in allowed_records]
    if len({node["name"] for node in nodes}) != len(_NODE_SPECS):
        raise ClusterResourceError("scheduler returned duplicate allowlisted nodes")
    nodes.sort(key=lambda node: node["name"])

    partitions = []
    for spec in _PARTITION_SPECS:
        partition_nodes = [node for node in nodes if node["partition"] == spec["name"]]
        if len(partition_nodes) != len(spec["nodes"]):
            raise ClusterResourceError("scheduler partition membership is incomplete")
        partitions.append(
            {
                "name": spec["name"],
                "gpu_model": spec["gpu_model"],
                "node_total": len(partition_nodes),
                "available_nodes": sum(
                    node["availability"] == "available" for node in partition_nodes
                ),
                "cpu": _sum_resource(partition_nodes, "cpu"),
                "memory_mib": _sum_resource(partition_nodes, "memory_mib"),
                "gpu": _sum_gpu(partition_nodes),
            }
        )

    gpu = _sum_gpu(nodes)
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)
    collected_at = collected_at.astimezone(timezone.utc)
    return {
        "status": "fresh",
        "stale": False,
        "collected_at": collected_at.isoformat(),
        "scheduler_updated_at": _scheduler_timestamp(payload.get("last_update")),
        "error_code": None,
        "summary": {
            "node_total": len(nodes),
            "available_nodes": sum(node["availability"] == "available" for node in nodes),
            "gpu_total": gpu["total"],
            "gpu_allocated": gpu["allocated"],
            "gpu_free": gpu["free"],
            "gpu_available": gpu["available"],
        },
        "partitions": partitions,
        "nodes": nodes,
    }


def _unavailable_snapshot() -> dict:
    return {
        "status": "unavailable",
        "stale": False,
        "collected_at": None,
        "scheduler_updated_at": None,
        "error_code": "cluster_snapshot_unavailable",
        "summary": {
            "node_total": 0,
            "available_nodes": 0,
            "gpu_total": None,
            "gpu_allocated": None,
            "gpu_free": None,
            "gpu_available": False,
        },
        "partitions": [],
        "nodes": [],
    }


class ClusterResourceService:
    def __init__(
        self,
        *,
        executor: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        timeout_seconds: float = 5.0,
        max_output_bytes: int = 1024 * 1024,
        cache_ttl_seconds: float = 10.0,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if timeout_seconds <= 0 or cache_ttl_seconds <= 0:
            raise ValueError("timeouts must be positive")
        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        self._executor = executor
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_bytes = int(max_output_bytes)
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._last_success: dict | None = None
        self._last_success_monotonic: float | None = None

    def _collect(self) -> dict:
        completed = self._executor(
            list(_SCONTROL_COMMAND),
            shell=False,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout_seconds,
        )
        if (
            _byte_length(completed.stdout) > self.max_output_bytes
            or _byte_length(completed.stderr) > self.max_output_bytes
        ):
            raise ClusterResourceError("scheduler output exceeded the configured limit")
        if int(completed.returncode) != 0 or _decode(completed.stderr).strip():
            raise ClusterResourceError("scheduler query failed")
        payload = json.loads(_decode(completed.stdout))
        return parse_cluster_resources(payload, self._wall_clock())

    def get_snapshot(self) -> dict:
        with self._lock:
            now = self._monotonic_clock()
            if (
                self._last_success is not None
                and self._last_success_monotonic is not None
                and now - self._last_success_monotonic < self.cache_ttl_seconds
            ):
                return copy.deepcopy(self._last_success)
            try:
                snapshot = self._collect()
            except (
                ClusterResourceError,
                OSError,
                OverflowError,
                subprocess.SubprocessError,
                TypeError,
                UnicodeError,
                ValueError,
            ):
                if self._last_success is None:
                    return _unavailable_snapshot()
                stale = copy.deepcopy(self._last_success)
                stale["status"] = "stale"
                stale["stale"] = True
                stale["error_code"] = "cluster_snapshot_refresh_failed"
                return stale
            self._last_success = snapshot
            self._last_success_monotonic = now
            return copy.deepcopy(snapshot)
