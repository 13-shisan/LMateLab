import importlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

class CompetitionAgentRegistrationTests(unittest.TestCase):
    def build_paths(self, enabled: str | None):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            (frontend / "index.html").write_text("ok", encoding="utf-8")
            environment = {
                "JWT_SECRET": "local-agent-registration-test-secret",
                "LMATELAB_FRONTEND_DIST": str(frontend),
                "LMATELAB_COORDINATOR_ENABLED": "0",
            }
            if enabled is not None:
                environment["LMATELAB_COMPETITION_AGENT_ENABLED"] = enabled
            with mock.patch.dict("os.environ", environment, clear=True):
                with mock.patch("auth_identity.JWT_SECRET", environment["JWT_SECRET"]):
                    module = importlib.import_module("main_107cup")
                    app = module.build_app(coordinator_enabled=False)
            return {route.path for route in app.routes}

    def test_default_off_keeps_existing_route_surface_unchanged(self):
        self.assertNotIn("/api/competition/agent/runs", self.build_paths(None))

    def test_explicit_enable_registers_dedicated_agent_routes(self):
        paths = self.build_paths("1")
        self.assertIn("/api/competition/agent/templates", paths)
        self.assertIn("/api/competition/agent/runs", paths)
        self.assertIn("/api/competition/agent/structures", paths)
        self.assertIn("/api/competition/agent/structures/build", paths)
        self.assertIn("/api/competition/agent/structures/bundle", paths)

    def test_invalid_flag_fails_startup(self):
        with self.assertRaisesRegex(ValueError, "must be 0 or 1"):
            self.build_paths("true")


if __name__ == "__main__":
    unittest.main()
