import hashlib
import json
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from auth_identity import get_current_user
from database import Base, get_db
from models import User
from models_workflow import (
    WorkflowAttempt,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
    canonical_json,
)
from routers.competition_workflows import (
    get_competition_coordinator,
    get_competition_reconciler,
    router,
    upload_structure,
)
from schemas_workflow import StructureUploadResult
from services.competition_inputs import InputValidationError, MAX_STRUCTURE_BYTES
from services.competition_coordinator import CoordinatorError
from services.competition_reconcile import CompetitionReconciler, ReconcileError
from services.competition_slurm import SlurmError
from services.competition_vasp import VaspPolicyError


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
        self.coordinator = mock.Mock()
        self.slurm_client = mock.Mock()
        self.coordinator.reconciler.slurm = self.slurm_client
        self.app.dependency_overrides[get_competition_coordinator] = (
            lambda: self.coordinator
        )
        self.cancel_service = mock.Mock()
        self.app.dependency_overrides[get_competition_reconciler] = lambda: self.cancel_service
        self.client = TestClient(self.app)

    def create_draft(self, owner_id=None, payload=None):
        self.identity_id = owner_id or self.operator_id
        response = self.client.post(
            "/api/competition/drafts",
            json=payload or valid_payload(),
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def test_default_reconciler_dependency_remains_available(self):
        self.assertIsInstance(get_competition_reconciler(), CompetitionReconciler)

    def create_validated_attempt(self, owner_id=None, status="running", metadata=None):
        draft = self.create_draft(owner_id=owner_id)
        confirmed = self.client.post(
            f"/api/competition/workflows/{draft['id']}/submit",
            json={},
        )
        self.assertEqual(200, confirmed.status_code, confirmed.text)
        attempt_id = str(uuid.uuid4())
        attempt_dir = self.workflow_root / draft["id"] / "attempts" / attempt_id
        attempt_dir.mkdir(parents=True)
        with Session(self.engine) as session:
            run = session.get(WorkflowRun, draft["id"])
            step = session.scalar(
                select(WorkflowStep)
                .where(WorkflowStep.workflow_id == run.id)
                .order_by(WorkflowStep.position)
            )
            run.status = status
            step.status = status
            session.add(
                WorkflowAttempt(
                    id=attempt_id,
                    step_id=step.id,
                    attempt_number=1,
                    status=status,
                    slurm_job_id="41050",
                    working_directory=str(attempt_dir),
                    metadata_json=metadata or {
                        "scheduler_observation": {
                            "error_code": None,
                            "exit_code": "0:0",
                            "observed_at": "2026-08-15T10:00:00+00:00",
                            "raw_state": "RUNNING",
                            "reason": "None",
                            "source": "squeue",
                            "stale": False,
                            "state": status,
                        }
                    },
                )
            )
            session.commit()
        return draft, attempt_id

    @staticmethod
    def coordinator_outcome(workflow_id, attempt_id, step_key="relax", status="queued"):
        return SimpleNamespace(
            workflow_id=workflow_id,
            attempt_id=attempt_id,
            step_key=step_key,
            status=status,
        )

    @staticmethod
    def cancellation_outcome(workflow_id, attempt_id, status="cancelling"):
        return SimpleNamespace(
            workflow_id=workflow_id,
            attempt_id=attempt_id,
            job_id="41050",
            status=status,
            result="requested",
        )

    @staticmethod
    def acceptance_metadata(*, accepted, reason_code=None):
        check = {"name": "scheduler_state", "passed": accepted}
        if not accepted:
            check["reason_code"] = reason_code
        report = {
            "accepted": accepted,
            "reason_code": reason_code,
            "checks": [check],
            "measurements": {
                "elapsed_wall_seconds": 1.25,
                "process_tree_peak_rss_kbytes": 2048,
                "vasp_version": "6.4.2",
                "vaspkit_version": "1.5.1",
            },
            "artifacts": [
                {"name": "OUTCAR", "sha256": "a" * 64, "size_bytes": 123}
            ],
        }
        report_sha256 = hashlib.sha256(
            canonical_json(report).encode("utf-8")
        ).hexdigest()
        return {
            "scheduler_observation": {
                "raw_state": "COMPLETED",
                "exit_code": "0:0",
                "reason": f"private reason at /home/{'accepted' if accepted else 'failed'}",
                "error_code": None,
            },
            "scientific_acceptance": report,
            "scientific_acceptance_sha256": report_sha256,
        }

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
            self.assertIsNone(step["attempt_id"])
            self.assertIsNone(step["job_id"])
            self.assertEqual(0, step["attempt"])
            self.assertIsNone(step["attempt_dir"])
            self.assertIsNone(step["slurm_state"])
        self.assertNotIn("relative_path", response.text)
        self.assertNotIn(str(self.workflow_root), response.text)
        self.assertEqual(404, self.client.get(f"/api/competition/workflows/{other['id']}").status_code)
        self.assertEqual(404, self.client.get("/api/competition/workflows/missing").status_code)

    def test_detail_and_list_expose_latest_attempt_without_absolute_paths(self):
        draft, attempt_id = self.create_validated_attempt()

        detail = self.client.get(f"/api/competition/workflows/{draft['id']}")
        listing = self.client.get("/api/competition/workflows")

        self.assertEqual(200, detail.status_code, detail.text)
        step = detail.json()["steps"][0]
        self.assertEqual(attempt_id, step["attempt_id"])
        self.assertEqual("41050", step["job_id"])
        self.assertEqual(1, step["attempt"])
        self.assertEqual(f"{draft['id']}/attempts/{attempt_id}", step["attempt_dir"])
        self.assertEqual("RUNNING", step["slurm_state"])
        self.assertEqual("0:0", step["exit_code"])
        self.assertIsNone(step["reason"])
        self.assertIsNone(step["accepted"])
        self.assertIsNone(step["acceptance"])
        self.assertEqual({}, step["resources"])
        self.assertIsNotNone(step["updated_at"])
        self.assertNotIn(str(self.workflow_root), detail.text)
        item = next(row for row in listing.json()["items"] if row["id"] == draft["id"])
        self.assertEqual("41050", item["latest_job_id"])
        self.assertEqual("relax", item["current_step"])

    def test_step_attempt_id_rejects_malformed_and_noncanonical_ledger_ids(self):
        for tampered_attempt_id in (
            "not-a-uuid/private-attempt",
            str(uuid.uuid4()).upper(),
        ):
            with self.subTest(tampered_attempt_id=tampered_attempt_id):
                draft, attempt_id = self.create_validated_attempt()
                with Session(self.engine) as session:
                    attempt = session.get(WorkflowAttempt, attempt_id)
                    attempt.id = tampered_attempt_id
                    session.commit()

                response = self.client.get(
                    f"/api/competition/workflows/{draft['id']}"
                )

                self.assertEqual(200, response.status_code, response.text)
                step = response.json()["steps"][0]
                self.assertIsNone(step["attempt_id"])
                self.assertNotIn(tampered_attempt_id, response.text)

    def test_list_and_dashboard_reject_tampered_historical_job_ids(self):
        draft, attempt_id = self.create_validated_attempt(status="running")
        private_job_id = "/home/private/job-41050\nraw scheduler text"
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, attempt_id)
            attempt.slurm_job_id = private_job_id
            run = session.get(WorkflowRun, draft["id"])
            run.status = "running"
            session.commit()

        listing = self.client.get("/api/competition/workflows")
        dashboard = self.client.get("/api/competition/dashboard")

        self.assertEqual(200, listing.status_code, listing.text)
        self.assertEqual(200, dashboard.status_code, dashboard.text)
        item = next(row for row in listing.json()["items"] if row["id"] == draft["id"])
        self.assertIsNone(item["latest_job_id"])
        recent = next(
            row
            for row in dashboard.json()["recent_workflows"]
            if row["id"] == draft["id"]
        )
        self.assertIsNone(recent["latest_job_id"])
        self.assertIsNone(dashboard.json()["active_workflow"]["latest_job_id"])
        self.assertNotIn(private_job_id, listing.text)
        self.assertNotIn(private_job_id, dashboard.text)
        self.assertNotIn("/home/private", listing.text)
        self.assertNotIn("/home/private", dashboard.text)

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
        self.assertEqual("idle", body["slurm"]["state"])

    def test_dashboard_scheduler_summary_uses_only_visible_attempt_ledger(self):
        own, _attempt_id = self.create_validated_attempt(status="running")
        self.create_validated_attempt(owner_id=self.other_id, status="queued")
        self.identity_id = self.operator_id

        response = self.client.get("/api/competition/dashboard")

        self.assertEqual(200, response.status_code, response.text)
        slurm = response.json()["slurm"]
        self.assertEqual({"queued": 0, "running": 1, "state": "running"}, {
            key: slurm[key] for key in ("queued", "running", "state")
        })
        self.assertEqual(own["id"], response.json()["active_workflow"]["id"])
        self.assertNotIn("Other Name", response.text)
        self.assertNotIn(str(self.workflow_root), response.text)

    def test_operator_workflow_commands_are_thin_and_duplicate_safe(self):
        draft, attempt_id = self.create_validated_attempt()
        command_outcome = self.coordinator_outcome(draft["id"], attempt_id)
        cancel_outcome = self.cancellation_outcome(draft["id"], attempt_id)
        self.coordinator.start.return_value = command_outcome
        self.coordinator.retry.return_value = command_outcome
        self.coordinator.cancel.return_value = cancel_outcome

        start_first = self.client.post(
            f"/api/competition/workflows/{draft['id']}/start", json={}
        )
        start_second = self.client.post(
            f"/api/competition/workflows/{draft['id']}/start"
        )
        retry_first = self.client.post(
            f"/api/competition/workflows/{draft['id']}/steps/relax/retry", json={}
        )
        retry_second = self.client.post(
            f"/api/competition/workflows/{draft['id']}/steps/relax/retry"
        )
        cancel_first = self.client.post(
            f"/api/competition/workflows/{draft['id']}/cancel", json={}
        )
        cancel_second = self.client.post(
            f"/api/competition/workflows/{draft['id']}/cancel"
        )

        for response in (
            start_first,
            start_second,
            retry_first,
            retry_second,
            cancel_first,
            cancel_second,
        ):
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(attempt_id, response.json()["attempt_id"])
        self.assertEqual(start_first.json(), start_second.json())
        self.assertEqual(retry_first.json(), retry_second.json())
        self.assertEqual(cancel_first.json(), cancel_second.json())
        self.coordinator.start.assert_has_calls(
            [mock.call(draft["id"], self.operator_id)] * 2
        )
        self.coordinator.retry.assert_has_calls(
            [mock.call(draft["id"], self.operator_id, "relax")] * 2
        )
        self.coordinator.cancel.assert_has_calls(
            [mock.call(draft["id"], self.operator_id)] * 2
        )

        injected = self.client.post(
            f"/api/competition/workflows/{draft['id']}/cancel",
            json={"job_id": "99999"},
        )
        self.assertEqual(422, injected.status_code, injected.text)
        self.assertEqual(2, self.coordinator.cancel.call_count)

    def test_workflow_commands_reject_every_body_override_before_coordinator(self):
        workflow_id = str(uuid.uuid4())
        for suffix in ("start", "steps/scf/retry", "cancel"):
            for key, value in (
                ("job_id", "99999"),
                ("path", "/home/private"),
                ("filename", "private.out"),
                ("limit", 999999),
                ("unknown", "private scheduler input"),
            ):
                with self.subTest(suffix=suffix, key=key):
                    response = self.client.post(
                        f"/api/competition/workflows/{workflow_id}/{suffix}",
                        json={key: value},
                    )
                    self.assertEqual(422, response.status_code, response.text)
        self.coordinator.start.assert_not_called()
        self.coordinator.retry.assert_not_called()
        self.coordinator.cancel.assert_not_called()

    def test_workflow_commands_authenticate_before_lookup_and_validate_paths(self):
        workflow_id = str(uuid.uuid4())
        self.identity_id = self.viewer_id
        for suffix in ("start", "steps/scf/retry", "cancel"):
            with self.subTest(suffix=suffix):
                response = self.client.post(
                    f"/api/competition/workflows/{workflow_id}/{suffix}", json={}
                )
                self.assertEqual(403, response.status_code, response.text)
        self.coordinator.assert_not_called()
        self.coordinator.start.assert_not_called()
        self.coordinator.retry.assert_not_called()
        self.coordinator.cancel.assert_not_called()

        unauthenticated = FastAPI()
        unauthenticated.include_router(router, prefix="/api")
        unauthenticated_client = TestClient(unauthenticated)
        for suffix in (
            "not-a-uuid/start",
            f"{workflow_id}/steps/foreign/retry",
            "not-a-uuid/cancel",
        ):
            with self.subTest(actor="unauthenticated", suffix=suffix):
                response = unauthenticated_client.post(
                    f"/api/competition/workflows/{suffix}", json={}
                )
                self.assertEqual(401, response.status_code, response.text)

        self.identity_id = self.viewer_id
        for suffix in (
            "not-a-uuid/start",
            f"{workflow_id}/steps/foreign/retry",
            "not-a-uuid/cancel",
        ):
            with self.subTest(actor="viewer", suffix=suffix):
                response = self.client.post(
                    f"/api/competition/workflows/{suffix}", json={}
                )
                self.assertEqual(403, response.status_code, response.text)

        self.identity_id = self.operator_id
        malformed = self.client.post(
            "/api/competition/workflows/not-a-uuid/start", json={}
        )
        invalid_step = self.client.post(
            f"/api/competition/workflows/{workflow_id}/steps/foreign/retry", json={}
        )
        self.assertEqual(422, malformed.status_code, malformed.text)
        self.assertEqual(422, invalid_step.status_code, invalid_step.text)
        self.coordinator.start.assert_not_called()
        self.coordinator.retry.assert_not_called()

    def test_workflow_command_errors_are_stable_and_sanitized(self):
        workflow_id = str(uuid.uuid4())
        secret = f"private scheduler output at {self.workflow_root}"
        cases = (
            ("start", CoordinatorError("workflow_not_found", secret), 404, "workflow_not_found"),
            (
                "start",
                CoordinatorError("workflow_not_startable", secret),
                409,
                "workflow_not_startable",
            ),
            (
                "steps/scf/retry",
                CoordinatorError("step_not_retryable", secret),
                409,
                "step_not_retryable",
            ),
            ("cancel", CoordinatorError("submission_failed", secret), 503, "submission_failed"),
            (
                "start",
                ReconcileError("scheduler_unavailable", secret),
                503,
                "scheduler_unavailable",
            ),
            ("start", SlurmError(secret), 503, "scheduler_unavailable"),
            (
                "start",
                VaspPolicyError("workflow_scope_invalid", secret),
                422,
                "workflow_scope_invalid",
            ),
            (
                "start",
                VaspPolicyError("potcar_sha256_mismatch", secret),
                422,
                "potcar_sha256_mismatch",
            ),
        )
        for suffix, error, expected_status, expected_code in cases:
            with self.subTest(code=expected_code):
                self.coordinator.reset_mock()
                method = (
                    self.coordinator.retry
                    if "/retry" in suffix
                    else self.coordinator.cancel
                    if suffix == "cancel"
                    else self.coordinator.start
                )
                method.side_effect = error
                response = self.client.post(
                    f"/api/competition/workflows/{workflow_id}/{suffix}", json={}
                )
                self.assertEqual(expected_status, response.status_code, response.text)
                self.assertEqual(expected_code, response.headers.get("X-Error-Code"))
                self.assertNotIn(secret, response.text)
                self.assertNotIn(str(self.workflow_root), response.text)
                method.side_effect = None

    def test_owned_operator_and_viewer_read_only_bounded_ledger_logs(self):
        draft, attempt_id = self.create_validated_attempt()
        self.slurm_client.read_log_tail.return_value = "last bounded lines\n"
        path = (
            f"/api/competition/workflows/{draft['id']}"
            f"/attempts/{attempt_id}/logs/stdout"
        )

        operator = self.client.get(path)
        self.identity_id = self.viewer_id
        viewer = self.client.get(path)

        for response in (operator, viewer):
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(
                {"stream": "stdout", "content": "last bounded lines\n"},
                response.json(),
            )
        self.assertEqual(
            [mock.call(draft["id"], attempt_id, "stdout")] * 2,
            self.slurm_client.read_log_tail.call_args_list,
        )

        self.identity_id = self.operator_id
        self.slurm_client.read_log_tail.reset_mock()
        self.slurm_client.read_log_tail.return_value = "x" * (64 * 1024)
        bounded = self.client.get(path)
        self.assertEqual(200, bounded.status_code, bounded.text[:500])
        self.assertLessEqual(len(bounded.content), 64 * 1024 + 64)

        multibyte = ('\u6c49\u5b57"\\\n\U0001f642' * 20000) + "UTF8-tail"
        self.slurm_client.read_log_tail.return_value = multibyte
        escaped = self.client.get(path)
        self.assertEqual(200, escaped.status_code, escaped.text[:500])
        self.assertLessEqual(len(escaped.content), 64 * 1024 + 64)
        escaped.content.decode("utf-8")
        returned = escaped.json()["content"]
        self.assertTrue(multibyte.endswith(returned))
        self.assertTrue(returned.endswith("UTF8-tail"))

    def test_log_route_fails_closed_before_any_unsafe_read(self):
        own, own_attempt = self.create_validated_attempt()
        other, other_attempt = self.create_validated_attempt(owner_id=self.other_id)
        self.identity_id = self.operator_id
        valid_base = f"/api/competition/workflows/{own['id']}/attempts/{own_attempt}/logs"
        cases = (
            (f"/api/competition/workflows/{other['id']}/attempts/{other_attempt}/logs/stdout", 404),
            (f"/api/competition/workflows/{own['id']}/attempts/{other_attempt}/logs/stdout", 404),
            (f"/api/competition/workflows/{own['id']}/attempts/{uuid.uuid4()}/logs/stdout", 404),
            (f"/api/competition/workflows/not-a-uuid/attempts/{own_attempt}/logs/stdout", 422),
            (f"/api/competition/workflows/{own['id']}/attempts/not-a-uuid/logs/stdout", 422),
            (f"{valid_base}/combined", 422),
            (f"{valid_base}/stdout?limit=1", 422),
        )
        for path, expected in cases:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(expected, response.status_code, response.text)
        body_override = self.client.request(
            "GET", f"{valid_base}/stdout", json={"path": "/home/private"}
        )
        self.assertEqual(422, body_override.status_code, body_override.text)
        self.slurm_client.read_log_tail.assert_not_called()

        unauthenticated = FastAPI()
        unauthenticated.include_router(router, prefix="/api")
        unauthenticated.dependency_overrides[get_db] = self.app.dependency_overrides[get_db]
        response = TestClient(unauthenticated).get(f"{valid_base}/stdout")
        self.assertEqual(401, response.status_code, response.text)
        self.slurm_client.read_log_tail.assert_not_called()

    def test_log_route_returns_empty_missing_log_and_sanitizes_unsafe_reads(self):
        draft, attempt_id = self.create_validated_attempt()
        path = (
            f"/api/competition/workflows/{draft['id']}"
            f"/attempts/{attempt_id}/logs/stderr"
        )
        self.slurm_client.read_log_tail.return_value = ""
        missing = self.client.get(path)
        self.assertEqual({"stream": "stderr", "content": ""}, missing.json())

        self.slurm_client.read_log_tail.side_effect = ValueError(
            f"symlink at {self.workflow_root}"
        )
        unsafe = self.client.get(path)
        self.assertEqual(409, unsafe.status_code, unsafe.text)
        self.assertEqual("log_read_unsafe", unsafe.headers.get("X-Error-Code"))
        self.assertNotIn(str(self.workflow_root), unsafe.text)

        self.slurm_client.read_log_tail.side_effect = SlurmError(
            f"scheduler at {self.workflow_root}"
        )
        unavailable = self.client.get(path)
        self.assertEqual(503, unavailable.status_code, unavailable.text)
        self.assertEqual("scheduler_unavailable", unavailable.headers.get("X-Error-Code"))
        self.assertNotIn(str(self.workflow_root), unavailable.text)

    def test_step_serialization_distinguishes_scientific_acceptance_safely(self):
        expected_keys = {
            "key",
            "status",
            "job_id",
            "attempt",
            "attempt_id",
            "attempt_dir",
            "slurm_state",
            "exit_code",
            "reason",
            "accepted",
            "acceptance",
            "resources",
            "updated_at",
        }
        cases = (
            ("running", None, None),
            ("succeeded", True, None),
            ("scientific_failed", False, "electronic_not_converged"),
        )
        for attempt_status, expected_accepted, reason_code in cases:
            with self.subTest(attempt_status=attempt_status):
                metadata = (
                    self.acceptance_metadata(
                        accepted=expected_accepted,
                        reason_code=reason_code,
                    )
                    if expected_accepted is not None
                    else None
                )
                draft, _attempt_id = self.create_validated_attempt(
                    status=attempt_status,
                    metadata=metadata,
                )
                response = self.client.get(
                    f"/api/competition/workflows/{draft['id']}"
                )
                self.assertEqual(200, response.status_code, response.text)
                step = response.json()["steps"][0]
                self.assertEqual(expected_keys, set(step))
                self.assertIs(expected_accepted, step["accepted"])
                self.assertIsNotNone(step["updated_at"])
                if expected_accepted is None:
                    self.assertIsNone(step["acceptance"])
                    self.assertEqual({}, step["resources"])
                    self.assertIsNone(step["reason"])
                else:
                    self.assertIs(expected_accepted, step["acceptance"]["accepted"])
                    self.assertEqual(reason_code, step["reason"])
                    self.assertEqual(1.25, step["resources"]["elapsed_wall_seconds"])
                    self.assertEqual("a" * 64, step["acceptance"]["artifacts"][0]["sha256"])
                serialized = json.dumps(step)
                self.assertNotIn(str(self.workflow_root), serialized)
                self.assertNotIn("private reason", serialized)
                self.assertNotIn("POTCAR content", serialized)

    def test_tampered_acceptance_sha_and_status_fail_closed_without_leaks(self):
        secret = f"private acceptance at {self.workflow_root}"
        bad_sha = self.acceptance_metadata(accepted=True)
        bad_sha["scientific_acceptance_sha256"] = "0" * 64
        bad_sha["private"] = secret
        bad_status = self.acceptance_metadata(accepted=True)
        bad_status["private"] = secret
        cases = (
            ("succeeded", bad_sha),
            ("scientific_failed", bad_status),
        )
        for attempt_status, metadata in cases:
            with self.subTest(attempt_status=attempt_status):
                draft, _attempt_id = self.create_validated_attempt(
                    status=attempt_status,
                    metadata=metadata,
                )
                response = self.client.get(
                    f"/api/competition/workflows/{draft['id']}"
                )
                self.assertEqual(200, response.status_code, response.text)
                step = response.json()["steps"][0]
                self.assertIsNone(step["accepted"])
                self.assertIsNone(step["acceptance"])
                self.assertEqual({}, step["resources"])
                self.assertIsNone(step["reason"])
                self.assertNotIn(secret, response.text)
                self.assertNotIn(str(self.workflow_root), response.text)

    def test_cancel_endpoint_is_operator_owned_and_rejects_arbitrary_job_id(self):
        draft, attempt_id = self.create_validated_attempt()
        self.cancel_service.cancel_attempt.return_value = SimpleNamespace(
            workflow_id=draft["id"],
            attempt_id=attempt_id,
            job_id="41050",
            status="cancelling",
            result="requested",
        )

        response = self.client.post(
            f"/api/competition/workflows/{draft['id']}/attempts/{attempt_id}/cancel"
        )
        injected = self.client.post(
            f"/api/competition/workflows/{draft['id']}/attempts/{attempt_id}/cancel",
            json={"job_id": "99999"},
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("cancelling", response.json()["status"])
        self.assertEqual(422, injected.status_code, injected.text)
        self.cancel_service.cancel_attempt.assert_called_once()
        args = self.cancel_service.cancel_attempt.call_args.args
        self.assertEqual((draft["id"], attempt_id), args[1:])

        self.identity_id = self.viewer_id
        viewer = self.client.post(
            f"/api/competition/workflows/{draft['id']}/attempts/{attempt_id}/cancel"
        )
        self.assertEqual(403, viewer.status_code, viewer.text)

        other, other_attempt = self.create_validated_attempt(owner_id=self.other_id)
        self.identity_id = self.operator_id
        non_owner = self.client.post(
            f"/api/competition/workflows/{other['id']}/attempts/{other_attempt}/cancel"
        )
        self.assertEqual(404, non_owner.status_code, non_owner.text)

    def test_cancel_scheduler_errors_are_sanitized(self):
        draft, attempt_id = self.create_validated_attempt()
        self.cancel_service.cancel_attempt.side_effect = ReconcileError(
            "scheduler_unavailable",
            f"private output at {self.workflow_root}",
        )

        response = self.client.post(
            f"/api/competition/workflows/{draft['id']}/attempts/{attempt_id}/cancel"
        )

        self.assertEqual(503, response.status_code, response.text)
        self.assertEqual("scheduler service unavailable", response.json()["detail"])
        self.assertNotIn(str(self.workflow_root), response.text)

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
