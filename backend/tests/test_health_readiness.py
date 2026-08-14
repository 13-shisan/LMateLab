import os
import subprocess
import sys
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from routers import health


BACKEND_ROOT = Path(__file__).resolve().parents[1]
HEALTHCHECK_SCRIPT = BACKEND_ROOT / "healthcheck.py"


class HealthReadinessTests(unittest.TestCase):
    def setUp(self):
        if not hasattr(health, "database_readiness"):
            self.skipTest("database readiness helper is covered by the contract test")

    @staticmethod
    def engine_with_table(table_name: str):
        engine = create_engine("sqlite://")
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE TABLE {table_name} (id INTEGER)")
        return engine

    def test_database_readiness_requires_primary_and_digest_tables(self):
        with mock.patch.dict(os.environ, {"LMATELAB_EDITION": ""}):
            primary = self.engine_with_table("users")
            digest = self.engine_with_table("daily_digests")

            self.assertEqual(
                {"status": "ready"},
                health.database_readiness(primary, digest),
            )

            missing_primary = create_engine("sqlite://")
            with self.assertRaises(SQLAlchemyError):
                health.database_readiness(missing_primary, digest)

    def test_competition_readiness_requires_workflow_migration(self):
        primary = self.engine_with_table("users")
        digest = self.engine_with_table("daily_digests")

        with mock.patch.dict(os.environ, {"LMATELAB_EDITION": "107cup"}):
            with self.assertRaises(SQLAlchemyError):
                health.database_readiness(primary, digest)

            with primary.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE workflow_runs (id TEXT)")
            self.assertEqual(
                {"status": "ready"},
                health.database_readiness(primary, digest),
            )

    def test_standard_readiness_does_not_require_competition_tables(self):
        primary = self.engine_with_table("users")
        digest = self.engine_with_table("daily_digests")

        with mock.patch.dict(os.environ, {"LMATELAB_EDITION": "standard"}):
            self.assertEqual(
                {"status": "ready"},
                health.database_readiness(primary, digest),
            )


class HealthcheckScriptTests(unittest.TestCase):
    def setUp(self):
        if not HEALTHCHECK_SCRIPT.is_file():
            self.skipTest("healthcheck script is covered by the contract test")

    def run_healthcheck(self, ready_status: int):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                status = ready_status if self.path == "/api/health/ready" else 200
                self.send_response(status)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = os.environ.copy()
            env["HEALTHCHECK_BASE_URL"] = (
                f"http://127.0.0.1:{server.server_address[1]}"
            )
            result = subprocess.run(
                [sys.executable, str(HEALTHCHECK_SCRIPT)],
                cwd=BACKEND_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        return result, requests

    def test_healthcheck_accepts_database_ready_response(self):
        result, requests = self.run_healthcheck(200)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["/api/health/ready"], requests)

    def test_healthcheck_falls_back_only_for_old_images_without_ready_route(self):
        result, requests = self.run_healthcheck(404)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            ["/api/health/ready", "/api/academic-reports?page=1&page_size=1"],
            requests,
        )

    def test_healthcheck_rejects_database_not_ready_response(self):
        result, requests = self.run_healthcheck(503)

        self.assertNotEqual(0, result.returncode)
        self.assertEqual(["/api/health/ready"], requests)


class HealthReadinessContractTests(unittest.TestCase):
    def test_readiness_contract_is_present(self):
        self.assertTrue(
            hasattr(health, "database_readiness"),
            "routers.health.database_readiness is missing",
        )
        self.assertTrue(HEALTHCHECK_SCRIPT.is_file(), str(HEALTHCHECK_SCRIPT))


if __name__ == "__main__":
    unittest.main()
