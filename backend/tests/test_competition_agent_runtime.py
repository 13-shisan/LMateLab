import os
import json
import unittest
from unittest import mock

from services.competition_agent.qoder_runtime import (
    MockQoderRuntime,
    QoderRuntimeConfig,
    RealQoderRuntime,
)
from services.competition_agent.llm_runtime import LLMRuntimeConfig, OpenAICompatibleRuntime, llm_configured
from services.competition_agent.planning import apply_parameter_changes, calculation_plan, prepare_calculation_workspace
from services.competition_agent.vasp_analysis import analyze_vasp_files


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, body):
        self.body = body
        self.request = None

    def post(self, url, **kwargs):
        self.request = (url, kwargs)
        return FakeResponse(self.body)


class CompetitionAgentRuntimeTests(unittest.TestCase):
    def test_calculation_plan_finds_curated_mos2_and_band_template_chain(self):
        plan = calculation_plan("计算一下 MoS2 体系的能带")
        self.assertFalse(plan["needs_upload"])
        self.assertEqual(["relax", "scf", "band"], plan["steps"])
        self.assertEqual(
            ["17_2d_material_relax", "13_band_scf", "06_band_nscf"],
            [item["id"] for item in plan["templates"]],
        )

    def test_calculation_plan_requests_upload_when_structure_is_missing(self):
        plan = calculation_plan("计算一下 XeKr2 体系的能带")
        self.assertTrue(plan["needs_upload"])
        self.assertEqual("structure-not-found", plan["reason"])

    def test_uploaded_poscar_replaces_missing_structure_and_prepares_submission_workspace(self):
        poscar = """MoS2\n1.0\n3.18 0 0\n-1.59 2.75396 0\n0 0 20\nMo S\n1 2\nDirect\n0 0 0.5\n0.333333 0.666667 0.58\n0.666667 0.333333 0.42\n"""
        plan = calculation_plan("计算一下 MoS2 体系的能带", [{
            "id": "00000000-0000-4000-8000-000000000001",
            "name": "POSCAR",
            "category": "structure",
            "content": poscar,
        }])
        self.assertFalse(plan["needs_upload"])
        self.assertEqual("user-upload", plan["structures"][0]["source"])
        workspace = prepare_calculation_workspace(plan)
        self.assertTrue(workspace["workflow_compatible"])
        self.assertIn("POSCAR", workspace["files"])

    def test_single_uploaded_structure_wins_when_prompt_uses_a_material_nickname(self):
        poscar = """CuHHTP\n1.0\n3.18 0 0\n-1.59 2.75396 0\n0 0 20\nCu O\n1 2\nDirect\n0 0 0.5\n0.333333 0.666667 0.58\n0.666667 0.333333 0.42\n"""
        plan = calculation_plan("我想计算 CuHHTP 的能带", [{
            "id": "00000000-0000-4000-8000-000000000002",
            "name": "CuHHTP.vasp",
            "category": "structure",
            "content": poscar,
        }])
        self.assertFalse(plan["needs_upload"])
        self.assertEqual("CuHHTP", plan["material_formula"])
        self.assertEqual("CuHHTP.vasp", plan["structures"][0]["name"])
        self.assertEqual("user-upload", plan["prepared_structure"]["source"])

    def test_large_uploaded_structure_is_plannable_but_not_workflow_compatible(self):
        coordinates = "\n".join("0 0 0" for _ in range(228))
        poscar = (
            "CuHHTP\n1.0\n10 0 0\n0 10 0\n0 0 20\nCu\n228\nDirect\n"
            f"{coordinates}\n"
        )
        plan = calculation_plan("计算 CuHHTP 的能带", [{
            "id": "00000000-0000-4000-8000-000000000003",
            "name": "CuHHTP.vasp",
            "category": "structure",
            "content": poscar,
        }])
        self.assertFalse(plan["needs_upload"])
        self.assertEqual(228, plan["prepared_structure"]["summary"]["atom_count"])
        self.assertFalse(plan["prepared_structure"]["workflow_compatible"])

    def test_parameter_changes_only_modify_declared_template_placeholders(self):
        plan = calculation_plan("计算一下 MoS2 体系的能带")
        apply_parameter_changes(plan, [
            {
                "template_id": "17_2d_material_relax",
                "parameter": "ENCUT",
                "value": "520",
                "reason": "Use the pseudopotential convergence baseline.",
            },
            {
                "template_id": "17_2d_material_relax",
                "parameter": "NSW",
                "value": "999",
                "reason": "Fixed parameters cannot be changed by the LLM.",
            },
            {
                "template_id": "13_band_scf",
                "parameter": "ENCUT",
                "value": "520; rm -rf /",
                "reason": "Unsafe value.",
            },
        ])
        self.assertEqual(1, len(plan["parameter_changes"]))
        self.assertIn("ENCUT  = 520", plan["templates"][0]["rendered_content"])
        self.assertIn("NSW    = 160", plan["templates"][0]["rendered_content"])

    def test_predefined_vasp_analyzers_extract_result_facts(self):
        results = analyze_vasp_files([
            {
                "id": "file-1",
                "name": "OUTCAR",
                "content": (
                    "free  energy   TOTEN  = -12.34 eV\n"
                    "aborting loop because EDIFF is reached\n"
                    "reached required accuracy\n"
                ),
            },
            {
                "id": "file-2",
                "name": "OSZICAR",
                "content": " 1 F= -.1200E+02 E0= -.1210E+02 d E =-.1E+00 mag= 2.0\n",
            },
        ])
        self.assertEqual("outcar_summary_v1", results[0]["analyzer"])
        self.assertEqual(-12.34, results[0]["facts"]["final_energy_eV"])
        self.assertTrue(results[0]["facts"]["ionic_converged"])
        self.assertEqual("oszicar_summary_v1", results[1]["analyzer"])
        self.assertEqual(-12.1, results[1]["facts"]["final_energy_e0_eV"])

    def test_llm_runtime_uses_openai_compatible_api_and_validates_file_citation(self):
        file_id = "00000000-0000-0000-0000-000000000001"
        answer = json.dumps({
            "summary": "The calculation converged.",
            "citations": [{"kind": "file", "id": file_id}],
            "tool_calls": [],
            "workspace": {},
            "advisory_only": True,
        })
        client = FakeClient({"choices": [{"message": {"content": answer}}]})
        runtime = OpenAICompatibleRuntime(
            environ={
                "LMATELAB_LLM_API_URL": "https://api.llm.ustc.edu.cn/v1/chat/completions",
                "LMATELAB_LLM_MODEL": "glm-5.2",
                "LMATELAB_LLM_API_KEY": "secret",
            },
            client=client,
        )
        output = runtime.run(
            request_kind="file_analysis",
            prompt="Did it converge?",
            tool_payload={"files": [{"kind": "file", "id": file_id, "content": "ok"}]},
        )
        self.assertEqual("llm", output["provider"])
        self.assertNotIn("secret", repr(output))
        self.assertEqual("Bearer secret", client.request[1]["headers"]["Authorization"])
        self.assertEqual(file_id, output["citations"][0]["id"])

    def test_llm_config_requires_https_and_key(self):
        with self.assertRaisesRegex(RuntimeError, "HTTPS"):
            LLMRuntimeConfig.from_environ({"LMATELAB_LLM_API_URL": "http://example.test", "LMATELAB_LLM_API_KEY": "x"})
        with self.assertRaisesRegex(RuntimeError, "key is unavailable"):
            LLMRuntimeConfig.from_environ({})

    def test_llm_status_does_not_treat_missing_key_file_as_configured(self):
        self.assertFalse(llm_configured({"LMATELAB_LLM_API_KEY_FILE": "/missing/key"}))

    def test_production_policy_disables_builtin_tools_and_auto_modes(self):
        config = QoderRuntimeConfig.from_environ({})
        self.assertEqual("dontAsk", config.permission_mode)
        self.assertFalse(config.yolo)
        self.assertEqual((), config.allowed_builtin_tools)
        self.assertEqual(
            {"Bash", "Write", "Edit", "Read", "Glob", "WebFetch"},
            set(config.disabled_builtin_tools),
        )

    def test_mock_runtime_never_reads_personal_access_token(self):
        with mock.patch.dict(os.environ, {"QODERCN_PERSONAL_ACCESS_TOKEN": "must-not-be-read"}):
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

    def test_real_runtime_cli_auth_does_not_require_pat(self):
        runtime = RealQoderRuntime(environ={
            "LMATELAB_QODER_REAL_NETWORK_AUTHORIZED": "1",
            "LMATELAB_QODER_AUTH_MODE": "cli",
        })
        self.assertEqual("cli", runtime.config.auth_mode)

    def test_real_runtime_validates_advisory_json_and_citations(self):
        output = RealQoderRuntime._validated_output(
            json.dumps({
                "summary": "Use the controlled relaxation template.",
                "citations": [{"kind": "template", "id": "2d_relax"}],
                "tool_calls": [],
                "workspace": {},
                "advisory_only": True,
            }),
            "template_recommendation",
            {"templates": [{"id": "2d_relax"}]},
        )
        self.assertEqual("qoder", output["provider"])

    def test_real_runtime_rejects_unauthorized_citation(self):
        with self.assertRaisesRegex(RuntimeError, "unauthorized data"):
            RealQoderRuntime._validated_output(
                json.dumps({
                    "summary": "Unsafe citation.",
                    "citations": [{"kind": "template", "id": "unknown"}],
                    "tool_calls": [],
                    "workspace": {},
                    "advisory_only": True,
                }),
                "template_recommendation",
                {"templates": [{"id": "2d_relax"}]},
            )

    def test_llm_runtime_replaces_model_citations_with_server_authorized_sources(self):
        output = OpenAICompatibleRuntime._validated_output(
            json.dumps({"summary": "answer", "citations": [{"kind": "file", "id": "invented"}]}),
            {("template", "2d_relax")},
        )
        self.assertEqual([{"kind": "template", "id": "2d_relax"}], output["citations"])

    def test_llm_runtime_accepts_only_authorized_parameter_changes(self):
        plan = calculation_plan("计算一下 MoS2 体系的能带")
        output = OpenAICompatibleRuntime._validated_output(
            json.dumps({
                "summary": "Use a converged cutoff.",
                "parameter_changes": [
                    {"template_id": "17_2d_material_relax", "parameter": "ENCUT", "value": "520", "reason": "baseline"},
                    {"template_id": "17_2d_material_relax", "parameter": "NSW", "value": "999", "reason": "not editable"},
                ],
            }),
            {("template", "17_2d_material_relax")},
            {"plan": plan},
        )
        self.assertEqual(
            [{"template_id": "17_2d_material_relax", "parameter": "ENCUT", "value": "520", "reason": "baseline"}],
            output["parameter_changes"],
        )


if __name__ == "__main__":
    unittest.main()
