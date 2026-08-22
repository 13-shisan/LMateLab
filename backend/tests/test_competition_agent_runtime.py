import os
import unittest
from unittest import mock

from services.competition_agent.qoder_runtime import (
    MockQoderRuntime,
    QoderRuntimeConfig,
    RealQoderRuntime,
)


class CompetitionAgentRuntimeTests(unittest.TestCase):
    def test_production_policy_disables_builtin_tools_and_auto_modes(self):
        config = QoderRuntimeConfig.from_environ({})
        self.assertEqual("dont_ask", config.permission_mode)
        self.assertFalse(config.yolo)
        self.assertEqual((), config.allowed_builtin_tools)
        self.assertEqual(
            {"Bash", "Write", "Edit", "Read", "Glob", "WebFetch"},
            set(config.disabled_builtin_tools),
        )

    def test_mock_runtime_never_reads_personal_access_token(self):
        with mock.patch.dict(os.environ, {"QODER_PERSONAL_ACCESS_TOKEN": "must-not-be-read"}):
            with mock.patch.dict(os.environ, {}, clear=False):
                output = MockQoderRuntime().run(
                    request_kind="template_recommendation",
                    prompt="Recommend a safe MoS2 relax template",
                    tool_payload={
                        "templates": [{"id": "2d_relax"}],
                        "structure": {"material_id": "MoS2_monolayer", "files": {"POSCAR": "safe"}},
                    },
                )
        self.assertEqual("mock", output["provider"])
        self.assertNotIn("must-not-be-read", repr(output))
        self.assertEqual("MoS2_monolayer", output["workspace"]["structure"]["material_id"])
        self.assertEqual(
            [{"name": "build_curated_structure", "status": "succeeded"}],
            output["tool_calls"],
        )

    def test_real_runtime_fails_closed_without_explicit_enablement(self):
        with self.assertRaisesRegex(RuntimeError, "real Qoder runtime is not authorized"):
            RealQoderRuntime(environ={}).run(
                request_kind="template_recommendation",
                prompt="test",
                tool_payload={},
            )


if __name__ == "__main__":
    unittest.main()
