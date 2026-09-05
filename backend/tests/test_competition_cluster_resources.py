from __future__ import annotations

import json
import subprocess
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth_identity import get_current_user
from routers.competition_cluster import (
    get_cluster_resource_service,
    router,
)
from services.competition_cluster_resources import ClusterResourceService


def _node(number: int, **overrides):
    is_rtx = number <= 15
    gpu_type = "RTX5090" if is_rtx else "A100"
    partition = "P107-RTX5090" if is_rtx else "P107-A100"
    node = {
        "name": f"anode{number:02d}",
        "state": ["IDLE"],
        "partitions": [partition, "Students"],
        "cpus": 128,
        "alloc_cpus": 0,
        "alloc_idle_cpus": 128,
        "real_memory": 512000 if is_rtx else 1024000,
        "alloc_memory": 0,
        "free_mem": {"set": True, "infinite": False, "number": 400000},
        "gres": f"gpu:{gpu_type}:8",
        "gres_used": f"gpu:{gpu_type}:0(IDX:N/A)",
        "owner": "must-not-leak",
        "address": f"11.11.10.{number}",
        "reason_set_by_user": "must-not-leak",
    }
    node.update(overrides)
    return node


def _payload():
    nodes = [_node(number) for number in range(1, 27)]
    nodes[0].update(
        state=["MIXED"],
        alloc_cpus=54,
        alloc_idle_cpus=74,
        gres_used="gpu:RTX5090:6(IDX:0-5)",
    )
    nodes[15].update(
        state=["ALLOCATED"],
        alloc_cpus=128,
        alloc_idle_cpus=0,
        gres_used="gpu:A100:8(IDX:0-7)",
    )
    nodes.append(
        {
            **_node(1),
            "name": "other-node",
            "partitions": ["Students"],
            "owner": "other-user",
        }
    )
    return {
        "nodes": nodes,
        "last_update": {"set": True, "infinite": False, "number": 1788618075},
        "errors": [],
        "warnings": [],
        "meta": {
            "client": {"user": "pb23030683", "group": "pb23030683"},
            "command": ["show"],
        },
    }


class _Executor:
    def __init__(self, payload=None, error=None):
        self.payload = _payload() if payload is None else payload
        self.error = error
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(self.payload).encode("utf-8"),
            stderr=b"",
        )


class ClusterResourceServiceTests(unittest.TestCase):
    def _service(self, executor, monotonic=None, max_output_bytes=1024 * 1024):
        return ClusterResourceService(
            executor=executor,
            timeout_seconds=5,
            max_output_bytes=max_output_bytes,
            cache_ttl_seconds=10,
            monotonic_clock=monotonic or (lambda: 100.0),
            wall_clock=lambda: datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
        )

    def test_fixed_bounded_command_parses_only_allowed_nodes(self):
        executor = _Executor()
        snapshot = self._service(executor).get_snapshot()

        self.assertEqual("fresh", snapshot["status"])
        self.assertFalse(snapshot["stale"])
        self.assertEqual("2026-09-05T12:00:00+00:00", snapshot["collected_at"])
        self.assertEqual(26, snapshot["summary"]["node_total"])
        self.assertEqual(25, snapshot["summary"]["available_nodes"])
        self.assertEqual(26, len(snapshot["nodes"]))
        self.assertEqual(["P107-RTX5090", "P107-A100"], [
            item["name"] for item in snapshot["partitions"]
        ])
        self.assertEqual(
            ["/usr/bin/scontrol", "--json", "show", "nodes", "anode[01-26]"],
            executor.calls[0][0],
        )
        self.assertEqual(
            {
                "shell": False,
                "check": False,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "timeout": 5.0,
            },
            executor.calls[0][1],
        )
        first = snapshot["nodes"][0]
        self.assertEqual("available", first["availability"])
        self.assertEqual({"total": 8, "allocated": 6, "free": 2, "available": True}, first["gpu"])
        self.assertEqual({"total": 128, "allocated": 54, "free": 74}, first["cpu"])
        encoded = json.dumps(snapshot, sort_keys=True)
        for sensitive in (
            "must-not-leak",
            "other-user",
            "pb23030683",
            "11.11.10.",
            "reason_set_by_user",
            '"command"',
            '"owner"',
        ):
            self.assertNotIn(sensitive, encoded)

    def test_gpu_missing_from_scheduler_is_explicitly_unavailable(self):
        payload = _payload()
        payload["nodes"][2]["gres_used"] = None
        snapshot = self._service(_Executor(payload)).get_snapshot()

        node = snapshot["nodes"][2]
        self.assertEqual(
            {"total": None, "allocated": None, "free": None, "available": False},
            node["gpu"],
        )
        self.assertEqual("unknown", node["availability"])
        rtx = snapshot["partitions"][0]
        self.assertFalse(rtx["gpu"]["available"])
        self.assertIsNone(rtx["gpu"]["free"])

    def test_cache_avoids_repeated_scheduler_queries_inside_ttl(self):
        now = [100.0]
        executor = _Executor()
        service = self._service(executor, monotonic=lambda: now[0])

        first = service.get_snapshot()
        now[0] = 109.9
        second = service.get_snapshot()

        self.assertEqual(first, second)
        self.assertEqual(1, len(executor.calls))

    def test_collection_failure_returns_last_success_as_stale(self):
        now = [100.0]
        executor = _Executor()
        service = self._service(executor, monotonic=lambda: now[0])
        fresh = service.get_snapshot()
        executor.error = subprocess.TimeoutExpired("scontrol", 5)
        now[0] = 111.0

        stale = service.get_snapshot()

        self.assertEqual("stale", stale["status"])
        self.assertTrue(stale["stale"])
        self.assertEqual("cluster_snapshot_refresh_failed", stale["error_code"])
        self.assertEqual(fresh["nodes"], stale["nodes"])
        self.assertEqual(fresh["collected_at"], stale["collected_at"])

    def test_first_failure_and_malformed_payload_fail_closed(self):
        cases = [
            _Executor(error=subprocess.TimeoutExpired("scontrol", 5)),
            _Executor({"nodes": [], "errors": [], "warnings": []}),
            _Executor({**_payload(), "warnings": ["partial data"]}),
        ]
        wrong_partition = _payload()
        wrong_partition["nodes"][0]["partitions"] = ["Students"]
        cases.append(_Executor(wrong_partition))
        for executor in cases:
            with self.subTest(executor=executor):
                snapshot = self._service(executor).get_snapshot()
                self.assertEqual(
                    {
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
                    },
                    snapshot,
                )

    def test_output_limit_fails_closed(self):
        snapshot = self._service(_Executor(), max_output_bytes=16).get_snapshot()
        self.assertEqual("unavailable", snapshot["status"])


class CompetitionClusterRouteTests(unittest.TestCase):
    def setUp(self):
        self.role = "operator"
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=self.role)
        self.service = mock.Mock()
        self.service.get_snapshot.return_value = {
            "status": "fresh",
            "stale": False,
            "nodes": [],
            "partitions": [],
        }
        app.dependency_overrides[get_cluster_resource_service] = lambda: self.service
        self.client = TestClient(app)

    def test_operator_and_viewer_can_read_the_snapshot(self):
        for role in ("operator", "viewer"):
            with self.subTest(role=role):
                self.role = role
                response = self.client.get("/api/competition/cluster-resources")
                self.assertEqual(200, response.status_code, response.text)
                self.assertEqual("fresh", response.json()["status"])
        self.assertEqual(2, self.service.get_snapshot.call_count)

    def test_non_competition_role_is_forbidden(self):
        self.role = "member"
        response = self.client.get("/api/competition/cluster-resources")
        self.assertEqual(403, response.status_code, response.text)


if __name__ == "__main__":
    unittest.main()
