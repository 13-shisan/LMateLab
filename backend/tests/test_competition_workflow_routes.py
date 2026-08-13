import tempfile
import unittest
from unittest import mock
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from auth_identity import get_current_user
from database import Base, get_db
from models import User
from models_workflow import WorkflowEvent, WorkflowRun
from routers.competition_workflows import router, upload_structure
from schemas_workflow import StructureUploadResult
from services.competition_inputs import InputValidationError, MAX_STRUCTURE_BYTES


VALID_POSCAR = b"""MoS2
1.0
3.180000 0.000000 0.000000
-1.590000 2.753961 0.000000
0.000000 0.000000 20.000000
Mo S
1 2
Direct
0.000000 0.000000 0.500000
0.333333 0.666667 0.578000
0.333333 0.666667 0.422000
"""

TEST_RELEASE_COMMIT = "b" * 40


def valid_payload(**overrides):
    payload = {
        "template_version": "mos2_v1",
        "source_kind": "builtin",
        "steps": ["relax", "scf", "band", "dos"],
        "parameters": {},
    }
    payload.update(overrides)
    return payload


class CompetitionWorkflowRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        temp_path = Path(self.temp_dir.name)
        self.workflow_root = temp_path / "workflow-root"
        environment = mock.patch.dict(
            "os.environ",
            {
                "LMATELAB_WORKFLOW_ROOT": str(self.workflow_root),
                "LMATELAB_GIT_COMMIT": TEST_RELEASE_COMMIT,
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.engine = create_engine(
            f"sqlite:///{temp_path / 'routes.sqlite'}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        with Session(self.engine) as session:
            operator = User(
                email="operator@example.com",
                password_hash="hash",
                name="Operator Name",
                alias="operator",
                role="operator",
            )
            other = User(
                email="other@example.com",
                password_hash="hash",
                name="Other Name",
                alias="other",
                role="operator",
            )
            viewer = User(
                email="viewer@example.com",
                password_hash="hash",
                name="Demo Viewer",
                alias="viewer",
                role="viewer",
            )
            session.add_all([operator, other, viewer])
            session.commit()
            self.operator_id = operator.id
            self.other_id = other.id
            self.viewer_id = viewer.id

        self.identity_id = self.operator_id
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api")

        def test_db():
            with Session(self.engine) as session:
                yield session

        def identity(db: Session = Depends(get_db)):
            return db.get(User, self.identity_id)

        self.app.dependency_overrides[get_db] = test_db
        self.app.dependency_overrides[get_current_user] = identity
        self.client = TestClient(self.app)

    def create_draft(self, owner_id=None, payload=None):
        self.identity_id = owner_id or self.operator_id
        response = self.client.post(
            "/api/competition/drafts",
            json=payload or valid_payload(),
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def test_operator_upload_save_confirm_uses_authenticated_owner(self):
        upload = self.client.post(
            "/api/competition/structures",
            files={"file": ("POSCAR", VALID_POSCAR, "application/octet-stream")},
        )
        self.assertEqual(201, upload.status_code, upload.text)
        upload_body = upload.json()
        self.assertEqual("MoS2", upload_body["summary"]["formula"])
        self.assertNotIn("relative_path", upload_body)

        draft = self.create_draft(
            payload=valid_payload(
                source_kind="upload",
                structure_upload_id=upload_body["id"],
            )
        )
        self.assertEqual("draft", draft["status"])
        self.assertNotIn("owner_id", draft)
        self.assertNotIn("email", draft)

        confirmed = self.client.post(
            f"/api/competition/workflows/{draft['id']}/submit",
            json={},
        )
        self.assertEqual(200, confirmed.status_code, confirmed.text)
        self.assertEqual("validated", confirmed.json()["status"])
        with Session(self.engine) as session:
            run = session.get(WorkflowRun, draft["id"])
            self.assertEqual(self.operator_id, run.owner_id)

    def test_oversize_upload_is_rejected_before_structure_service(self):
        with mock.patch(
            "routers.competition_workflows.stage_structure"
        ) as stage_structure_spy:
            response = self.client.post(
                "/api/competition/structures",
                files={
                    "file": (
                        "POSCAR",
                        b"x" * (MAX_STRUCTURE_BYTES + 1),
                        "application/octet-stream",
                    )
                },
            )

        self.assertEqual(422, response.status_code, response.text)
        stage_structure_spy.assert_not_called()
        self.assertNotIn(str(self.workflow_root), response.text)

    def test_exact_upload_limit_reaches_structure_service(self):
        expected = StructureUploadResult(
            id="upload-id",
            relative_path="private/not-serialized",
            size_bytes=MAX_STRUCTURE_BYTES,
            sha256="a" * 64,
            source_format="vasp",
            summary={"formula": "MoS2"},
        )
        with mock.patch(
            "routers.competition_workflows.stage_structure", return_value=expected
        ) as stage_structure_spy:
            response = self.client.post(
                "/api/competition/structures",
                files={"file": ("POSCAR", b"x" * MAX_STRUCTURE_BYTES)},
            )

        self.assertEqual(201, response.status_code, response.text)
        self.assertEqual(MAX_STRUCTURE_BYTES, len(stage_structure_spy.call_args.kwargs["content"]))
        self.assertNotIn("relative_path", response.text)

    def test_viewer_cannot_call_any_stage_five_write_route(self):
        self.identity_id = self.viewer_id
        cases = (
            ("/api/competition/structures", {"files": {"file": ("POSCAR", VALID_POSCAR)}}),
            ("/api/competition/drafts", {"json": valid_payload()}),
            ("/api/competition/workflows/missing/submit", {"json": {}}),
        )
        for path, kwargs in cases:
            with self.subTest(path=path):
                response = self.client.post(path, **kwargs)
                self.assertEqual(403, response.status_code, response.text)

    def test_unauthenticated_write_is_401(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_db] = self.app.dependency_overrides[get_db]
        response = TestClient(app).post(
            "/api/competition/drafts",
            json=valid_payload(),
        )
        self.assertEqual(401, response.status_code, response.text)

    def test_operator_list_filters_paginates_and_never_sees_other_owner(self):
        first = self.create_draft()
        second = self.create_draft()
        self.create_draft(owner_id=self.other_id)
        self.identity_id = self.operator_id
        response = self.client.get(
            "/api/competition/workflows",
            params={"query": second["id"], "status": "draft", "page": 1, "page_size": 1},
        )
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(1, body["total"])
        self.assertEqual(1, body["page"])
        self.assertEqual(1, body["page_size"])
        self.assertEqual([second["id"]], [item["id"] for item in body["items"]])
        serialized = response.text
        self.assertNotIn(first["id"], serialized)
        self.assertNotIn("Other Name", serialized)
        self.assertNotIn("other@example.com", serialized)

    def test_viewer_can_read_competition_workflows_without_sensitive_fields(self):
        own = self.create_draft()
        other = self.create_draft(owner_id=self.other_id)
        self.identity_id = self.viewer_id
        response = self.client.get("/api/competition/workflows")
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual({own["id"], other["id"]}, {item["id"] for item in body["items"]})
        self.assertNotIn("owner_id", response.text)
        self.assertNotIn("@example.com", response.text)

    def test_detail_is_owner_scoped_for_operator_and_missing_is_404(self):
        own = self.create_draft()
        other = self.create_draft(owner_id=self.other_id)
        self.identity_id = self.operator_id
        response = self.client.get(f"/api/competition/workflows/{own['id']}")
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual("live", body["data_kind"])
        self.assertEqual(TEST_RELEASE_COMMIT, body["release_commit"])
        self.assertEqual(["relax", "scf", "band", "dos"], [step["key"] for step in body["steps"]])
        for step in body["steps"]:
            self.assertIsNone(step["job_id"])
            self.assertEqual(0, step["attempt"])
            self.assertIsNone(step["attempt_dir"])
            self.assertIsNone(step["slurm_state"])
        self.assertNotIn("relative_path", response.text)
        self.assertNotIn(str(self.workflow_root), response.text)
        self.assertEqual(404, self.client.get(f"/api/competition/workflows/{other['id']}").status_code)
        self.assertEqual(404, self.client.get("/api/competition/workflows/missing").status_code)

    def test_dashboard_uses_real_owner_scoped_counts(self):
        draft = self.create_draft()
        validated = self.create_draft()
        response = self.client.post(f"/api/competition/workflows/{validated['id']}/submit", json={})
        self.assertEqual(200, response.status_code, response.text)
        self.create_draft(owner_id=self.other_id)
        self.identity_id = self.operator_id
        response = self.client.get("/api/competition/dashboard")
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual({"total": 2, "running": 0, "recent_succeeded": 0, "needs_attention": 0}, body["summary"])
        self.assertEqual({draft["id"], validated["id"]}, {item["id"] for item in body["recent_workflows"]})
        self.assertIsNone(body["active_workflow"])
        self.assertEqual("not-integrated", body["slurm"]["state"])

    def test_dashboard_counts_all_visible_rows_not_only_recent_page(self):
        for index in range(12):
            draft = self.create_draft()
            if index == 0:
                with Session(self.engine) as session:
                    run = session.get(WorkflowRun, draft["id"])
                    run.status = "validation_failed"
                    session.commit()

        response = self.client.get("/api/competition/dashboard")
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(12, body["summary"]["total"])
        self.assertEqual(1, body["summary"]["needs_attention"])
        self.assertEqual(10, len(body["recent_workflows"]))

    def test_results_and_database_are_live_empty_envelopes(self):
        results = self.client.get("/api/competition/results", params={"query": "MoS2", "status": "all"})
        database = self.client.get(
            "/api/competition/vasp/records",
            params={"query": "MoS2", "elements": "Mo,S", "element_mode": "only", "page": 2, "page_size": 20},
        )
        self.assertEqual(
            {"items": [], "total": 0, "data_kind": "live"},
            results.json(),
        )
        self.assertEqual(200, database.status_code, database.text)
        body = database.json()
        self.assertEqual([], body["items"])
        self.assertEqual(0, body["total"])
        self.assertEqual(2, body["page"])
        self.assertEqual(20, body["page_size"])
        self.assertEqual([], body["available_elements"])
        self.assertEqual({}, body["metadata"])
        self.assertEqual("live", body["data_kind"])

    def test_invalid_upload_and_payload_are_4xx_without_internal_paths(self):
        upload = self.client.post(
            "/api/competition/structures",
            files={"file": ("../POSCAR", VALID_POSCAR)},
        )
        self.assertEqual(422, upload.status_code, upload.text)
        self.assertNotIn(str(self.workflow_root), upload.text)
        payload = self.client.post(
            "/api/competition/drafts",
            json={**valid_payload(), "owner_id": self.other_id},
        )
        self.assertEqual(422, payload.status_code, payload.text)
        self.assertNotIn(str(self.workflow_root), payload.text)

    def test_failed_confirmation_returns_422_and_persists_sanitized_event(self):
        draft = self.create_draft()
        with Session(self.engine) as session:
            run = session.get(WorkflowRun, draft["id"])
            generated = next(row for row in run.files if row.source_kind == "generated")
            (self.workflow_root / generated.relative_path).write_text("tampered", encoding="utf-8")
        response = self.client.post(f"/api/competition/workflows/{draft['id']}/submit", json={})
        self.assertEqual(422, response.status_code, response.text)
        self.assertNotIn(str(self.workflow_root), response.text)
        with Session(self.engine) as session:
            run = session.get(WorkflowRun, draft["id"])
            self.assertEqual("validation_failed", run.status)
            event = session.scalar(
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_id == draft["id"])
                .where(WorkflowEvent.event_type == "validation_failed")
            )
            self.assertIsNotNone(event)
            self.assertNotIn(str(self.workflow_root), event.payload_json)


class UploadResourceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_file_is_closed_once_on_all_outcomes(self):
        current_user = mock.Mock(id=1)
        session = mock.Mock()
        successful_result = StructureUploadResult(
            id="upload-id",
            relative_path="private/not-serialized",
            size_bytes=1,
            sha256="a" * 64,
            source_format="vasp",
            summary={"formula": "MoS2"},
        )
        cases = (
            (b"x", successful_result, None),
            (b"x", InputValidationError("invalid structure"), HTTPException),
            (b"x" * (MAX_STRUCTURE_BYTES + 1), successful_result, HTTPException),
            (b"x", RuntimeError("database path /secret"), HTTPException),
        )

        for content, service_outcome, expected_error in cases:
            with self.subTest(service_outcome=type(service_outcome).__name__):
                upload = mock.Mock()
                upload.filename = "POSCAR"
                upload.read = mock.AsyncMock(return_value=content)
                upload.close = mock.AsyncMock()
                if isinstance(service_outcome, Exception):
                    service_patch = mock.patch(
                        "routers.competition_workflows.stage_structure",
                        side_effect=service_outcome,
                    )
                else:
                    service_patch = mock.patch(
                        "routers.competition_workflows.stage_structure",
                        return_value=service_outcome,
                    )
                with service_patch as stage_structure_spy:
                    if expected_error is None:
                        await upload_structure(upload, current_user, session)
                    else:
                        with self.assertRaises(expected_error):
                            await upload_structure(upload, current_user, session)
                upload.read.assert_awaited_once_with(MAX_STRUCTURE_BYTES + 1)
                upload.close.assert_awaited_once_with()
                if len(content) > MAX_STRUCTURE_BYTES:
                    stage_structure_spy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
