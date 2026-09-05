import json
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from auth_identity import get_current_user
from database import Base, get_db
from models import User
from models_competition_agent import AgentRun
from routers.competition_agent import router
from services.competition_agent.service import process_next_run


class CompetitionAgentRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 'agent.sqlite'}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        with Session(self.engine) as session:
            operator = User(email="operator@example.com", password_hash="x", name="Operator", alias="operator", role="operator")
            viewer = User(email="viewer@example.com", password_hash="x", name="Viewer", alias="viewer", role="viewer")
            session.add_all([operator, viewer])
            session.commit()
            self.operator_id = operator.id
            self.viewer_id = viewer.id

        self.identity_id = self.operator_id
        app = FastAPI()
        app.include_router(router, prefix="/api")

        def test_db():
            with Session(self.engine) as session:
                yield session

        def identity(db: Session = Depends(get_db)):
            return db.get(User, self.identity_id)

        app.dependency_overrides[get_db] = test_db
        app.dependency_overrides[get_current_user] = identity
        self.client = TestClient(app)

    def create_run(self):
        response = self.client.post(
            "/api/competition/agent/runs",
            json={
                "request_kind": "template_recommendation",
                "prompt": "Recommend a template for MoS2 relaxation",
                "material_id": "MoS2_monolayer",
                "step_key": "relax",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def test_feature_flag_defaults_off(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            response = self.client.get("/api/competition/agent/templates")
        self.assertEqual(404, response.status_code)

    def test_runtime_status_reports_qoder_without_exposing_credentials(self):
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "qoder",
            "LMATELAB_QODER_AUTH_MODE": "cli",
            "LMATELAB_QODER_CONNECTED": "1",
            "QODER_PERSONAL_ACCESS_TOKEN": "must-not-leak",
        }
        with mock.patch.dict("os.environ", environment, clear=True):
            response = self.client.get("/api/competition/agent/runtime")
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(
            {
                "provider": "qoder",
                "auth_mode": "cli",
                "connected": True,
                "qoder_available": True,
                "qoder": {
                    "interface": "qoder-agent-sdk",
                    "enabled": True,
                    "connected": True,
                    "auth_mode": "cli",
                    "model": None,
                },
            },
            response.json(),
        )
        self.assertNotIn("must-not-leak", response.text)

    def test_operator_can_manage_qoder_through_fixed_actions(self):
        managed = {
            "manageable": True,
            "installed": True,
            "authenticated": True,
            "version": "1.1.38",
            "username": "Operator",
            "service_running": False,
            "login_pending": False,
            "login_url": None,
            "last_error": None,
        }
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_QODER_MANAGEMENT_ENABLED": "1",
        }
        with (
            mock.patch.dict("os.environ", environment, clear=True),
            mock.patch("routers.competition_agent.qoder_status", return_value=managed),
            mock.patch("routers.competition_agent.install_qoder", return_value=managed) as install,
            mock.patch("routers.competition_agent.start_login", return_value=managed) as login,
            mock.patch("routers.competition_agent.start_service", return_value={**managed, "service_running": True}) as start,
            mock.patch("routers.competition_agent.stop_service", return_value=managed) as stop,
        ):
            runtime = self.client.get("/api/competition/agent/runtime")
            installed = self.client.post("/api/competition/agent/qoder/install")
            logged_in = self.client.post("/api/competition/agent/qoder/login")
            started = self.client.post("/api/competition/agent/qoder/service/start")
            stopped = self.client.post("/api/competition/agent/qoder/service/stop")
        self.assertTrue(runtime.json()["qoder"]["authenticated"])
        self.assertEqual(200, installed.status_code)
        self.assertEqual(200, logged_in.status_code)
        self.assertTrue(started.json()["service_running"])
        self.assertEqual(200, stopped.status_code)
        install.assert_called_once_with()
        login.assert_called_once_with()
        start.assert_called_once_with()
        stop.assert_called_once_with()

    def test_viewer_cannot_manage_qoder(self):
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_QODER_MANAGEMENT_ENABLED": "1",
        }
        self.identity_id = self.viewer_id
        with mock.patch.dict("os.environ", environment, clear=True):
            response = self.client.post("/api/competition/agent/qoder/service/start")
        self.assertEqual(403, response.status_code)

    def test_operator_uploads_text_and_uses_it_for_file_analysis(self):
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
            "LMATELAB_AGENT_UPLOADS_ROOT": self.temp_dir.name,
        }
        with mock.patch.dict("os.environ", environment, clear=True):
            uploaded = self.client.post(
                "/api/competition/agent/files",
                data={"category": "result"},
                files={"file": ("OUTCAR", b"free  energy   TOTEN  = -12.34 eV", "text/plain")},
            )
            self.assertEqual(201, uploaded.status_code, uploaded.text)
            file_id = uploaded.json()["id"]
            listed = self.client.get("/api/competition/agent/files")
            self.assertEqual([file_id], [item["id"] for item in listed.json()["items"]])
            created = self.client.post(
                "/api/competition/agent/runs",
                json={
                    "request_kind": "file_analysis",
                    "prompt": "Interpret the final energy",
                    "file_ids": [file_id],
                },
            )
        self.assertEqual(201, created.status_code, created.text)
        self.assertEqual(file_id, created.json()["input"]["files"][0]["id"])
        analysis = created.json()["input"]["analysis_results"][0]
        self.assertEqual("outcar_summary_v1", analysis["analyzer"])
        self.assertEqual(-12.34, analysis["facts"]["final_energy_eV"])

    def test_upload_categories_and_conversation_are_persisted(self):
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
            "LMATELAB_AGENT_UPLOADS_ROOT": self.temp_dir.name,
        }
        conversation_id = "00000000-0000-4000-8000-000000000099"
        with mock.patch.dict("os.environ", environment, clear=True):
            uploaded = self.client.post(
                "/api/competition/agent/files",
                data={"category": "incar-template"},
                files={"file": ("INCAR", b"ENCUT = 520", "text/plain")},
            )
            self.assertEqual("incar-template", uploaded.json()["category"])
            created = self.client.post("/api/competition/agent/runs", json={
                "request_kind": "general_qa",
                "prompt": "Explain this template",
                "file_ids": [uploaded.json()["id"]],
                "conversation_id": conversation_id,
            })
            listed = self.client.get("/api/competition/agent/runs")
        self.assertEqual(201, created.status_code, created.text)
        self.assertEqual(conversation_id, created.json()["conversation_id"])
        self.assertEqual(conversation_id, listed.json()["items"][0]["conversation_id"])

    def test_auto_request_kind_routes_qa_planning_and_result_analysis(self):
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
            "LMATELAB_AGENT_UPLOADS_ROOT": self.temp_dir.name,
        }
        calculation_id = "00000000-0000-4000-8000-000000000124"
        poscar = b"CuHHTP\n1.0\n3.18 0 0\n-1.59 2.75396 0\n0 0 20\nCu O\n1 2\nDirect\n0 0 0.5\n0.333333 0.666667 0.58\n0.666667 0.333333 0.42\n"
        with mock.patch.dict("os.environ", environment, clear=True):
            structure = self.client.post(
                "/api/competition/agent/files",
                data={"category": "structure"},
                files={"file": ("CuHHTP.vasp", poscar, "text/plain")},
            ).json()
            result = self.client.post(
                "/api/competition/agent/files",
                data={"category": "result", "calculation_id": calculation_id, "group_name": "CuHHTP-band"},
                files={"file": ("OUTCAR", b"free  energy   TOTEN  = -12.34 eV", "text/plain")},
            ).json()
            qa = self.client.post("/api/competition/agent/runs", json={
                "request_kind": "auto", "prompt": "这篇文献主要讨论了什么？",
            })
            planning = self.client.post("/api/competition/agent/runs", json={
                "request_kind": "auto", "prompt": "计算 CuHHTP 的能带", "file_ids": [structure["id"]],
            })
            analysis = self.client.post("/api/competition/agent/runs", json={
                "request_kind": "auto", "prompt": "分析这个计算是否收敛", "calculation_ids": [calculation_id],
            })
        self.assertEqual("general_qa", qa.json()["request_kind"])
        self.assertEqual("calculation_planning", planning.json()["request_kind"])
        self.assertFalse(planning.json()["input"]["plan"]["needs_upload"])
        self.assertEqual("result_analysis", analysis.json()["request_kind"])
        self.assertEqual(result["id"], analysis.json()["input"]["files"][0]["id"])
        self.assertEqual(
            {"requested": "auto", "resolved": "result_analysis"},
            analysis.json()["input"]["intent"],
        )

    def test_follow_up_includes_bounded_conversation_history_and_delete_removes_thread(self):
        conversation_id = "00000000-0000-4000-8000-000000000098"
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
        }
        with mock.patch.dict("os.environ", environment, clear=True):
            first = self.client.post("/api/competition/agent/runs", json={
                "request_kind": "general_qa",
                "prompt": "What is the reference energy?",
                "conversation_id": conversation_id,
            })
            with Session(self.engine) as session:
                completed = process_next_run(session)
                first_summary = json.loads(completed.output_json)["summary"]
            second = self.client.post("/api/competition/agent/runs", json={
                "request_kind": "general_qa",
                "prompt": "Compare it with the new value.",
                "conversation_id": conversation_id,
            })
            self.assertEqual(
                [{"user": "What is the reference energy?", "assistant": first_summary}],
                second.json()["input"]["conversation_history"],
            )
            active_delete = self.client.delete(
                f"/api/competition/agent/runs/conversations/{conversation_id}"
            )
            with Session(self.engine) as session:
                process_next_run(session)
            deleted = self.client.delete(
                f"/api/competition/agent/runs/conversations/{conversation_id}"
            )
            listed = self.client.get("/api/competition/agent/runs")
        self.assertEqual(201, first.status_code, first.text)
        self.assertEqual(201, second.status_code, second.text)
        self.assertEqual(409, active_delete.status_code)
        self.assertEqual(204, deleted.status_code, deleted.text)
        self.assertEqual([], listed.json()["items"])

    def test_literature_upload_contract_and_citation_metadata_are_visible(self):
        from pypdf import PdfWriter

        pdf = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_metadata({"/Title": "MoS2 reference"})
        writer.write(pdf)
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
            "LMATELAB_AGENT_UPLOADS_ROOT": self.temp_dir.name,
            "LMATELAB_LITERATURE_DB": str(Path(self.temp_dir.name) / "literature.sqlite"),
        }
        indexed_payload = {
            "source_id": "openalex:W456",
            "title": "Band structure of MoS2",
            "abstract": "Band dispersion and density of states.",
            "authors": ["A. Author"],
            "year": 2024,
            "doi": "10.1000/mos2",
            "url": "https://doi.org/10.1000/mos2",
            "library_name": "电子结构",
        }

        class CitationRuntime:
            provider = "mock"

            def run(self, **_kwargs):
                return {
                    "summary": "Literature-grounded answer.",
                    "citations": [{"kind": "literature", "id": "openalex:W456"}],
                    "tool_calls": [],
                    "workspace": {},
                    "parameter_changes": [],
                    "advisory_only": True,
                }

        with mock.patch.dict("os.environ", environment, clear=True):
            # A blank PDF has no extractable text and must fail visibly rather than disappear.
            rejected = self.client.post(
                "/api/competition/agent/files",
                data={"category": "literature"},
                files={"file": ("blank.pdf", pdf.getvalue(), "application/pdf")},
            )
            uploaded = self.client.post(
                "/api/competition/agent/files",
                data={"category": "literature", "library_name": "电子结构"},
                files={"file": ("notes.md", b"MoS2 has a direct monolayer gap.", "text/markdown")},
            )
            library = self.client.get("/api/competition/agent/literature")
            indexed = self.client.post("/api/competition/agent/literature/index", json=indexed_payload)
            created = self.client.post("/api/competition/agent/runs", json={
                "request_kind": "general_qa",
                "prompt": "What does the paper report?",
                "literature_ids": ["openalex:W456"],
            })
            with Session(self.engine) as session:
                completed = process_next_run(session, runtime=CitationRuntime())
                output = json.loads(completed.output_json)
        self.assertEqual(422, rejected.status_code)
        self.assertEqual(201, uploaded.status_code, uploaded.text)
        self.assertEqual("notes.md", library.json()["uploads"][0]["name"])
        self.assertEqual(201, indexed.status_code, indexed.text)
        self.assertEqual(201, created.status_code, created.text)
        self.assertEqual("Band structure of MoS2", output["citations"][0]["title"])
        self.assertEqual("https://doi.org/10.1000/mos2", output["citations"][0]["url"])

    def test_operator_builds_an_owner_scoped_literature_index(self):
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_LITERATURE_DB": str(Path(self.temp_dir.name) / "literature.sqlite"),
        }
        payload = {
            "source_id": "openalex:W123",
            "title": "First-principles study of MoS2",
            "abstract": "A converged plane-wave calculation.",
            "authors": ["A. Researcher"],
            "year": 2025,
            "doi": "10.1000/example",
            "url": "https://doi.org/10.1000/example",
            "library_name": "MoS2 项目",
        }
        with mock.patch.dict("os.environ", environment, clear=True):
            indexed = self.client.post("/api/competition/agent/literature/index", json=payload)
            listed = self.client.get("/api/competition/agent/literature")
            self.identity_id = self.viewer_id
            denied = self.client.get("/api/competition/agent/literature")
        self.assertEqual(201, indexed.status_code, indexed.text)
        self.assertEqual("MoS2 项目", listed.json()["items"][0]["library_name"])
        self.assertEqual(403, denied.status_code)

    def test_dawn5_examples_are_seeded_and_analyzed_as_result_files(self):
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
            "LMATELAB_AGENT_UPLOADS_ROOT": self.temp_dir.name,
            "LMATELAB_AGENT_EXAMPLES_ENABLED": "1",
        }
        with mock.patch.dict("os.environ", environment, clear=True):
            listed = self.client.get("/api/competition/agent/files")
            examples = listed.json()["items"]
            outcars = [item for item in examples if item["name"] == "OUTCAR"]
            created = self.client.post("/api/competition/agent/runs", json={
                "request_kind": "result_analysis",
                "prompt": "Compare the two converged SCF energies",
                "file_ids": [item["id"] for item in outcars],
            })
        self.assertEqual(10, len(examples))
        self.assertEqual(2, len(outcars))
        self.assertTrue(all(item["builtin_example"] for item in outcars))
        self.assertEqual(
            ["Dawn5 / Cr2C12Se6F6 SCF", "Dawn5 / Cr2C12O6F6 SCF"],
            [item["group_name"] for item in outcars],
        )
        energies = [item["facts"]["final_energy_eV"] for item in created.json()["input"]["analysis_results"]]
        self.assertEqual([-169.84809903, -188.11837156], energies)

    def test_result_analysis_mounts_calculation_directories_and_selects_files_for_prompt(self):
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
            "LMATELAB_AGENT_UPLOADS_ROOT": self.temp_dir.name,
        }
        calculation_id = "00000000-0000-4000-8000-000000000123"
        with mock.patch.dict("os.environ", environment, clear=True):
            for name, content in (
                ("OUTCAR", b"free  energy   TOTEN  = -12.34 eV"),
                ("EIGENVAL", b"header\nheader\nheader\nheader\nheader\n8 4 12\n"),
                ("DOSCAR", b"header\nheader\nheader\nheader\nheader\n0 0 4 5.5\n"),
            ):
                response = self.client.post(
                    "/api/competition/agent/files",
                    data={
                        "category": "result",
                        "calculation_id": calculation_id,
                        "group_name": "MoS2-band",
                    },
                    files={"file": (name, content, "text/plain")},
                )
                self.assertEqual(201, response.status_code, response.text)
            listed = self.client.get("/api/competition/agent/files").json()
            created = self.client.post("/api/competition/agent/runs", json={
                "request_kind": "result_analysis",
                "prompt": "分析这个体系的能带",
                "calculation_ids": [calculation_id],
            })
        self.assertEqual(1, len(listed["calculations"]))
        self.assertEqual("MoS2-band", listed["calculations"][0]["name"])
        self.assertEqual(
            ["EIGENVAL", "OUTCAR"],
            [item["name"] for item in created.json()["input"]["files"]],
        )
        self.assertNotIn("DOSCAR", [item["name"] for item in created.json()["input"]["files"]])

    def test_dawn5_example_bundle_is_bounded_and_excludes_restricted_files(self):
        with mock.patch.dict("os.environ", {"LMATELAB_COMPETITION_AGENT_ENABLED": "1"}, clear=True):
            listed = self.client.get("/api/competition/agent/examples")
            bundle = self.client.get("/api/competition/agent/examples/cr2c12o6f6-scf/bundle")
        self.assertEqual(2, len(listed.json()["items"]))
        self.assertEqual("application/zip", bundle.headers["content-type"])
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            names = archive.namelist()
        self.assertIn("OUTCAR", names)
        self.assertIn("MANIFEST.txt", names)
        self.assertNotIn("POTCAR", names)
        self.assertNotIn("WAVECAR", names)

    def test_agent_upload_is_owner_scoped(self):
        environment = {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
            "LMATELAB_AGENT_UPLOADS_ROOT": self.temp_dir.name,
        }
        with mock.patch.dict("os.environ", environment, clear=True):
            uploaded = self.client.post(
                "/api/competition/agent/files",
                files={"file": ("INCAR", b"ENCUT = 520", "text/plain")},
            ).json()
            self.identity_id = self.viewer_id
            denied = self.client.post(
                "/api/competition/agent/runs",
                json={"request_kind": "file_analysis", "prompt": "analyze", "file_ids": [uploaded["id"]]},
            )
        self.assertEqual(403, denied.status_code)

    def test_operator_can_create_mock_run_and_viewer_cannot(self):
        with mock.patch.dict("os.environ", {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
        }):
            created = self.create_run()
            self.assertEqual("queued", created["status"])
            self.assertEqual("mock", created["provider"])
            self.identity_id = self.viewer_id
            denied = self.client.post(
                "/api/competition/agent/runs",
                json={"request_kind": "template_recommendation", "prompt": "test", "material_id": "MoS2_monolayer", "step_key": "relax"},
            )
        self.assertEqual(403, denied.status_code)

    def test_viewer_reads_only_approved_persisted_analysis(self):
        with mock.patch.dict("os.environ", {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
        }):
            created = self.create_run()
            self.identity_id = self.viewer_id
            hidden = self.client.get(f"/api/competition/agent/runs/{created['id']}")
            self.assertEqual(404, hidden.status_code)
            with Session(self.engine) as session:
                run = session.get(AgentRun, created["id"])
                run.status = "succeeded"
                run.output_json = {"summary": "Approved analysis", "citations": []}
                run.approved_by_id = self.operator_id
                run.approved_at = run.updated_at
                session.commit()
            visible = self.client.get(f"/api/competition/agent/runs/{created['id']}")
        self.assertEqual(200, visible.status_code, visible.text)
        self.assertEqual("Approved analysis", visible.json()["output"]["summary"])
        self.assertEqual("", visible.json()["prompt"])
        self.assertEqual({}, visible.json()["input"])

    def test_create_worker_approve_viewer_flow_uses_persisted_mock_output(self):
        with mock.patch.dict("os.environ", {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
        }):
            created = self.create_run()
            with Session(self.engine) as session:
                processed = process_next_run(session)
                self.assertEqual(created["id"], processed.id)
                self.assertEqual("succeeded", processed.status)
            completed = self.client.get(f"/api/competition/agent/runs/{created['id']}")
            self.assertEqual(200, completed.status_code, completed.text)
            self.assertTrue(completed.json()["output"]["advisory_only"])
            approved = self.client.post(f"/api/competition/agent/runs/{created['id']}/approve")
            self.assertEqual(200, approved.status_code, approved.text)
            self.assertTrue(approved.json()["approved"])
            self.identity_id = self.viewer_id
            visible = self.client.get(f"/api/competition/agent/runs/{created['id']}")
        self.assertEqual(200, visible.status_code, visible.text)
        self.assertEqual("", visible.json()["prompt"])

    def test_calculation_plan_survives_llm_timeout_with_explicit_fallback(self):
        class TimeoutRuntime:
            provider = "mock"

            def run(self, **_kwargs):
                raise TimeoutError("provider timed out")

        with mock.patch.dict("os.environ", {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
        }):
            created = self.client.post(
                "/api/competition/agent/runs",
                json={
                    "request_kind": "calculation_planning",
                    "prompt": "计算一下 MoS2 体系的能带",
                },
            )
            self.assertEqual(201, created.status_code, created.text)
            with Session(self.engine) as session:
                processed = process_next_run(session, runtime=TimeoutRuntime())
                output = json.loads(processed.output_json)
        self.assertEqual("succeeded", processed.status)
        self.assertEqual("provider-timeout", output["llm_status"])
        self.assertEqual(["relax", "scf", "band"], output["workspace"]["plan"]["steps"])
        self.assertEqual("failed", output["tool_calls"][-1]["status"])

    def test_non_mos2_sample_builds_a_workspace_without_an_executable_template(self):
        with mock.patch.dict("os.environ", {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
        }):
            response = self.client.post(
                "/api/competition/agent/runs",
                json={
                    "request_kind": "template_recommendation",
                    "prompt": "Prepare a graphene structure and explain the available templates",
                    "material_id": "graphene",
                    "step_key": "relax",
                },
            )
            self.assertEqual(201, response.status_code, response.text)
            with Session(self.engine) as session:
                processed = process_next_run(session)
                output = json.loads(processed.output_json)
        self.assertEqual("graphene", output["workspace"]["structure"]["material_id"])
        self.assertEqual([], output["citations"])
        self.assertIn("没有适用模板", output["summary"])

    def test_curated_structure_catalog_build_and_bundle_enforce_roles(self):
        payload = {
            "material_id": "MoS2_monolayer",
            "repeat_a": 2,
            "repeat_b": 1,
            "layers": 1,
            "vacuum_angstrom": 18.0,
            "interlayer_spacing_angstrom": 6.2,
            "strain_percent": 0.0,
        }
        with mock.patch.dict("os.environ", {
            "LMATELAB_COMPETITION_AGENT_ENABLED": "1",
            "LMATELAB_COMPETITION_AGENT_PROVIDER": "mock",
        }):
            catalog = self.client.get("/api/competition/agent/structures")
            self.assertEqual(200, catalog.status_code, catalog.text)
            self.assertEqual(6, len(catalog.json()["items"]))

            built = self.client.post("/api/competition/agent/structures/build", json=payload)
            self.assertEqual(200, built.status_code, built.text)
            self.assertEqual(6, built.json()["summary"]["atom_count"])
            self.assertNotIn("POTCAR", built.json()["files"])

            bundle = self.client.post("/api/competition/agent/structures/bundle", json=payload)
            self.assertEqual(200, bundle.status_code, bundle.text)
            self.assertEqual("application/zip", bundle.headers["content-type"])
            self.assertIn("MoS2_monolayer-vasp-inputs.zip", bundle.headers["content-disposition"])

            invalid = self.client.post(
                "/api/competition/agent/structures/build",
                json={**payload, "material_id": "unknown"},
            )
            self.assertEqual(422, invalid.status_code)

            self.identity_id = self.viewer_id
            visible = self.client.get("/api/competition/agent/structures")
            denied = self.client.post("/api/competition/agent/structures/build", json=payload)
        self.assertEqual(200, visible.status_code)
        self.assertEqual(403, denied.status_code)


if __name__ == "__main__":
    unittest.main()
