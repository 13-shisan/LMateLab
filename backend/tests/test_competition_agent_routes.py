import json
import tempfile
import unittest
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

    def test_operator_can_create_mock_run_and_viewer_cannot(self):
        with mock.patch.dict("os.environ", {"LMATELAB_COMPETITION_AGENT_ENABLED": "1"}):
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
        with mock.patch.dict("os.environ", {"LMATELAB_COMPETITION_AGENT_ENABLED": "1"}):
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
        with mock.patch.dict("os.environ", {"LMATELAB_COMPETITION_AGENT_ENABLED": "1"}):
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

    def test_non_mos2_sample_builds_a_workspace_without_an_executable_template(self):
        with mock.patch.dict("os.environ", {"LMATELAB_COMPETITION_AGENT_ENABLED": "1"}):
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
        with mock.patch.dict("os.environ", {"LMATELAB_COMPETITION_AGENT_ENABLED": "1"}):
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
