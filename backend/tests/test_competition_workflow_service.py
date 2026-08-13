import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from database import Base
from models import User
from models_workflow import (
    WorkflowAttempt,
    WorkflowEvent,
    WorkflowFile,
    WorkflowRun,
    WorkflowStep,
    WorkflowTemplate,
)
from schemas_workflow import DraftCreateRequest
from services.competition_inputs import InputValidationError
from services import competition_workflows as workflow_service
from services.competition_workflows import (
    WorkflowServiceError,
    _claim_upload,
    confirm_workflow,
    create_draft,
    stage_structure,
)


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


def valid_payload(**overrides):
    payload = {
        "template_version": "mos2_v1",
        "source_kind": "builtin",
        "steps": ["relax", "scf", "band", "dos"],
        "parameters": {},
    }
    payload.update(overrides)
    return DraftCreateRequest.model_validate(payload)


class CompetitionWorkflowServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name) / "workflow-root"
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 'workflows.sqlite'}",
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        with Session(self.engine) as session:
            owner = User(
                email="owner@example.com",
                password_hash="hash",
                name="owner",
                alias="",
                role="operator",
            )
            other = User(
                email="other@example.com",
                password_hash="hash",
                name="other",
                alias="",
                role="operator",
            )
            session.add_all([owner, other])
            session.commit()
            self.owner_id = owner.id
            self.other_id = other.id

    def test_stage_structure_keeps_private_raw_bytes_and_auditable_metadata(self):
        with Session(self.engine) as session:
            result = stage_structure(
                session,
                self.root,
                owner_id=self.owner_id,
                content=VALID_POSCAR,
                filename="POSCAR",
            )

        self.assertEqual(result.sha256, hashlib.sha256(VALID_POSCAR).hexdigest())
        self.assertEqual(result.size_bytes, len(VALID_POSCAR))
        self.assertEqual(result.source_format, "vasp")
        self.assertEqual(result.summary["formula"], "MoS2")
        self.assertNotIn(str(self.root), result.relative_path)
        stored_path = self.root / result.relative_path
        self.assertEqual(stored_path.read_bytes(), VALID_POSCAR)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(stored_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(stored_path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(stored_path.parent.parent.stat().st_mode), 0o700)

        with Session(self.engine) as session:
            row = session.get(WorkflowFile, result.id)
            self.assertEqual(row.owner_id, self.owner_id)
            self.assertIsNone(row.workflow_id)
            self.assertIsNone(row.attempt_id)
            self.assertEqual(row.relative_path, result.relative_path)
            metadata = json.loads(row.metadata_json)
            self.assertEqual(metadata["original_filename"], "POSCAR")
            self.assertEqual(metadata["structure_summary"]["formula"], "MoS2")
            self.assertFalse(metadata["consumed"])

    def test_stage_structure_failure_leaves_no_file_or_database_record(self):
        with Session(self.engine) as session:
            with self.assertRaises(InputValidationError):
                stage_structure(
                    session,
                    self.root,
                    owner_id=self.owner_id,
                    content=b"not a structure",
                    filename="POSCAR",
                )
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WorkflowFile)), 0)
        self.assertFalse(any(self.root.rglob("*")) if self.root.exists() else False)

    def test_stage_structure_commit_failure_compensates_completed_file(self):
        with Session(self.engine) as session:
            with mock.patch.object(session, "commit", side_effect=RuntimeError("db unavailable")):
                with self.assertRaises(RuntimeError):
                    stage_structure(
                        session,
                        self.root,
                        owner_id=self.owner_id,
                        content=VALID_POSCAR,
                        filename="POSCAR",
                    )
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WorkflowFile)), 0)
        files = [path for path in self.root.rglob("*") if path.is_file()] if self.root.exists() else []
        self.assertEqual(files, [])

    def test_create_builtin_draft_persists_fixed_graph_files_event_and_repeatable_hash(self):
        hashes = []
        run_ids = []
        for _ in range(2):
            with Session(self.engine) as session:
                result = create_draft(
                    session,
                    self.root,
                    owner_id=self.owner_id,
                    payload=valid_payload(),
                )
                hashes.append(result.input_sha256)
                run_ids.append(result.id)

        self.assertEqual(hashes[0], hashes[1])
        with Session(self.engine) as session:
            run = session.get(WorkflowRun, run_ids[0])
            self.assertEqual(run.status, "draft")
            self.assertEqual(run.input_sha256, hashes[0])
            steps = session.scalars(
                select(WorkflowStep)
                .where(WorkflowStep.workflow_id == run.id)
                .order_by(WorkflowStep.position)
            ).all()
            self.assertEqual([step.step_key for step in steps], ["relax", "scf", "band", "dos"])
            self.assertEqual([step.status for step in steps], ["waiting"] * 4)
            files = session.scalars(
                select(WorkflowFile).where(WorkflowFile.workflow_id == run.id)
            ).all()
            self.assertEqual(len(files), 16)
            self.assertTrue(all(not Path(row.relative_path).is_absolute() for row in files))
            events = session.scalars(
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_id == run.id)
                .order_by(WorkflowEvent.sequence)
            ).all()
            self.assertEqual([(event.sequence, event.event_type) for event in events], [(1, "draft_created")])
            self.assertEqual(session.scalar(select(func.count()).select_from(WorkflowAttempt)), 0)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(WorkflowTemplate)),
                1,
            )

    def test_uploaded_structure_is_owner_only_and_consumed_once(self):
        with Session(self.engine) as session:
            upload = stage_structure(
                session,
                self.root,
                owner_id=self.owner_id,
                content=VALID_POSCAR,
                filename="POSCAR",
            )

        upload_payload = valid_payload(
            source_kind="upload",
            structure_upload_id=upload.id,
        )
        with Session(self.engine) as session:
            with self.assertRaises(WorkflowServiceError) as denied:
                create_draft(
                    session,
                    self.root,
                    owner_id=self.other_id,
                    payload=upload_payload,
                )
            self.assertEqual(denied.exception.code, "upload_unavailable")

        with Session(self.engine) as session:
            run = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=upload_payload,
            )
        with Session(self.engine) as session:
            row = session.get(WorkflowFile, upload.id)
            self.assertEqual(row.workflow_id, run.id)
            self.assertTrue(json.loads(row.metadata_json)["consumed"])
            with self.assertRaises(WorkflowServiceError) as consumed:
                create_draft(
                    session,
                    self.root,
                    owner_id=self.owner_id,
                    payload=upload_payload,
                )
            self.assertEqual(consumed.exception.code, "upload_unavailable")

    def test_database_claim_allows_only_one_session_to_consume_stale_upload(self):
        with Session(self.engine) as session:
            upload = stage_structure(
                session,
                self.root,
                owner_id=self.owner_id,
                content=VALID_POSCAR,
                filename="POSCAR",
            )
            runs = [
                WorkflowRun(
                    owner_id=self.owner_id,
                    template_version="mos2_v1",
                    material="MoS2",
                    source_kind="upload",
                )
                for _ in range(2)
            ]
            session.add_all(runs)
            session.commit()
            run_ids = [run.id for run in runs]

        first = Session(self.engine)
        second = Session(self.engine)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        stale_first = first.get(WorkflowFile, upload.id)
        stale_second = second.get(WorkflowFile, upload.id)
        self.assertIsNone(stale_first.workflow_id)
        self.assertIsNone(stale_second.workflow_id)

        self.assertTrue(_claim_upload(first, stale_first, run_ids[0]))
        first.commit()
        self.assertFalse(_claim_upload(second, stale_second, run_ids[1]))
        second.rollback()

        with Session(self.engine) as session:
            row = session.get(WorkflowFile, upload.id)
            self.assertEqual(row.workflow_id, run_ids[0])
            metadata = json.loads(row.metadata_json)
            self.assertTrue(metadata["consumed"])
            self.assertEqual(metadata["consumed_by_workflow_id"], run_ids[0])

    def test_lost_upload_claim_rolls_back_draft_and_cleans_generated_inputs(self):
        with Session(self.engine) as session:
            upload = stage_structure(
                session,
                self.root,
                owner_id=self.owner_id,
                content=VALID_POSCAR,
                filename="POSCAR",
            )
        upload_path = self.root / upload.relative_path
        payload = valid_payload(
            source_kind="upload",
            structure_upload_id=upload.id,
        )

        with Session(self.engine) as session:
            with mock.patch(
                "services.competition_workflows._claim_upload",
                return_value=False,
            ):
                with self.assertRaises(WorkflowServiceError) as lost:
                    create_draft(
                        session,
                        self.root,
                        owner_id=self.owner_id,
                        payload=payload,
                    )
            self.assertEqual(lost.exception.code, "upload_unavailable")

        self.assertEqual(upload_path.read_bytes(), VALID_POSCAR)
        self.assertEqual(
            [
                path
                for path in self.root.iterdir()
                if path.is_dir() and path.name != "incoming"
            ],
            [],
        )
        with Session(self.engine) as session:
            upload_row = session.get(WorkflowFile, upload.id)
            self.assertIsNone(upload_row.workflow_id)
            self.assertFalse(json.loads(upload_row.metadata_json)["consumed"])
            self.assertEqual(session.scalar(select(func.count()).select_from(WorkflowRun)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(WorkflowStep)), 0)

    def test_draft_commit_failure_cleans_generated_inputs_but_preserves_upload_evidence(self):
        with Session(self.engine) as session:
            upload = stage_structure(
                session,
                self.root,
                owner_id=self.owner_id,
                content=VALID_POSCAR,
                filename="POSCAR",
            )
        upload_path = self.root / upload.relative_path
        payload = valid_payload(
            source_kind="upload",
            structure_upload_id=upload.id,
        )

        with Session(self.engine) as session:
            with mock.patch.object(session, "commit", side_effect=RuntimeError("db unavailable")):
                with self.assertRaises(RuntimeError):
                    create_draft(
                        session,
                        self.root,
                        owner_id=self.owner_id,
                        payload=payload,
                    )

        self.assertEqual(upload_path.read_bytes(), VALID_POSCAR)
        generated_directories = [
            path
            for path in self.root.iterdir()
            if path.is_dir() and path.name != "incoming"
        ]
        self.assertEqual(generated_directories, [])
        with Session(self.engine) as session:
            row = session.get(WorkflowFile, upload.id)
            self.assertIsNone(row.workflow_id)
            self.assertFalse(json.loads(row.metadata_json)["consumed"])
            self.assertEqual(session.scalar(select(func.count()).select_from(WorkflowRun)), 0)

    def test_result_serialization_failure_after_commit_preserves_persisted_inputs(self):
        with Session(self.engine) as session:
            with mock.patch(
                "services.competition_workflows._result",
                side_effect=RuntimeError("serialization failed"),
            ):
                with self.assertRaises(RuntimeError):
                    create_draft(
                        session,
                        self.root,
                        owner_id=self.owner_id,
                        payload=valid_payload(),
                    )

        with Session(self.engine) as session:
            run = session.scalar(select(WorkflowRun))
            self.assertIsNotNone(run)
            files = session.scalars(
                select(WorkflowFile).where(WorkflowFile.workflow_id == run.id)
            ).all()
            self.assertEqual(len(files), 16)
            self.assertTrue(all((self.root / row.relative_path).is_file() for row in files))

    def test_missing_upload_and_non_owner_confirmation_fail_closed(self):
        missing_payload = valid_payload(
            source_kind="upload",
            structure_upload_id="00000000-0000-0000-0000-000000000001",
        )
        with Session(self.engine) as session:
            with self.assertRaises(WorkflowServiceError) as missing:
                create_draft(
                    session,
                    self.root,
                    owner_id=self.owner_id,
                    payload=missing_payload,
                )
            self.assertEqual(missing.exception.code, "upload_unavailable")

            run = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=valid_payload(),
            )
        with Session(self.engine) as session:
            with self.assertRaises(WorkflowServiceError) as denied:
                confirm_workflow(
                    session,
                    self.root,
                    owner_id=self.other_id,
                    workflow_id=run.id,
                )
            self.assertEqual(denied.exception.code, "workflow_not_found")

    def test_confirmation_is_idempotent_and_never_creates_execution_state(self):
        with Session(self.engine) as session:
            draft = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=valid_payload(),
            )
        with Session(self.engine) as session:
            first = confirm_workflow(
                session,
                self.root,
                owner_id=self.owner_id,
                workflow_id=draft.id,
            )
            second = confirm_workflow(
                session,
                self.root,
                owner_id=self.owner_id,
                workflow_id=draft.id,
            )
            self.assertEqual(first.status, "validated")
            self.assertEqual(second.status, "validated")

        with Session(self.engine) as session:
            run = session.get(WorkflowRun, draft.id)
            self.assertEqual(run.status, "validated")
            self.assertEqual(
                session.scalars(
                    select(WorkflowEvent.event_type)
                    .where(WorkflowEvent.workflow_id == draft.id)
                    .order_by(WorkflowEvent.sequence)
                ).all(),
                ["draft_created", "workflow_validated"],
            )
            self.assertEqual(
                session.scalars(
                    select(WorkflowStep.status).where(WorkflowStep.workflow_id == draft.id)
                ).all(),
                ["waiting"] * 4,
            )
            self.assertEqual(session.scalar(select(func.count()).select_from(WorkflowAttempt)), 0)
        self.assertFalse((self.root / "attempts").exists())

    def test_stale_sessions_cannot_both_confirm_the_same_draft(self):
        with Session(self.engine) as session:
            draft = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=valid_payload(),
            )

        first = Session(self.engine, expire_on_commit=False)
        second = Session(self.engine, expire_on_commit=False)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        first_run = first.get(WorkflowRun, draft.id)
        second_run = second.get(WorkflowRun, draft.id)
        self.assertEqual(first_run.status, "draft")
        self.assertEqual(second_run.status, "draft")
        first.commit()
        second.commit()

        first_result = confirm_workflow(
            first,
            self.root,
            owner_id=self.owner_id,
            workflow_id=draft.id,
        )
        second_result = confirm_workflow(
            second,
            self.root,
            owner_id=self.owner_id,
            workflow_id=draft.id,
        )
        self.assertEqual(first_result.status, "validated")
        self.assertEqual(second_result.status, "validated")

        with Session(self.engine) as session:
            validated_events = session.scalars(
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_id == draft.id)
                .where(WorkflowEvent.event_type == "workflow_validated")
            ).all()
            self.assertEqual(len(validated_events), 1)

    def test_stale_validation_failure_cannot_overwrite_validated_winner(self):
        with Session(self.engine) as session:
            draft = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=valid_payload(),
            )
            file_row = session.scalar(
                select(WorkflowFile)
                .where(WorkflowFile.workflow_id == draft.id)
                .where(WorkflowFile.source_kind == "generated")
            )
            input_path = self.root / file_row.relative_path

        winner = Session(self.engine, expire_on_commit=False)
        loser = Session(self.engine, expire_on_commit=False)
        self.addCleanup(winner.close)
        self.addCleanup(loser.close)
        self.assertEqual(winner.get(WorkflowRun, draft.id).status, "draft")
        self.assertEqual(loser.get(WorkflowRun, draft.id).status, "draft")
        winner.commit()
        loser.commit()

        winner_result = confirm_workflow(
            winner,
            self.root,
            owner_id=self.owner_id,
            workflow_id=draft.id,
        )
        input_path.write_bytes(input_path.read_bytes() + b"tamper")
        loser_result = confirm_workflow(
            loser,
            self.root,
            owner_id=self.owner_id,
            workflow_id=draft.id,
        )
        self.assertEqual(winner_result.status, "validated")
        self.assertEqual(loser_result.status, "validated")

        with Session(self.engine) as session:
            run = session.get(WorkflowRun, draft.id)
            self.assertEqual(run.status, "validated")
            event_types = session.scalars(
                select(WorkflowEvent.event_type)
                .where(WorkflowEvent.workflow_id == draft.id)
                .order_by(WorkflowEvent.sequence)
            ).all()
            self.assertEqual(event_types, ["draft_created", "workflow_validated"])

    def test_confirmation_revalidates_files_after_discarding_a_stale_read_transaction(self):
        with Session(self.engine) as session:
            draft = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=valid_payload(),
            )
            file_row = session.scalar(
                select(WorkflowFile)
                .where(WorkflowFile.workflow_id == draft.id)
                .where(WorkflowFile.source_kind == "generated")
            )
            input_path = self.root / file_row.relative_path

        with Session(self.engine) as session:
            self.assertEqual(session.get(WorkflowRun, draft.id).status, "draft")
            original_rollback = session.rollback
            rollback_count = 0

            def rollback_and_tamper():
                nonlocal rollback_count
                original_rollback()
                rollback_count += 1
                if rollback_count == 1:
                    input_path.write_bytes(input_path.read_bytes() + b"tamper")

            with mock.patch.object(session, "rollback", side_effect=rollback_and_tamper):
                with self.assertRaises(WorkflowServiceError) as failed:
                    confirm_workflow(
                        session,
                        self.root,
                        owner_id=self.owner_id,
                        workflow_id=draft.id,
                    )

            self.assertEqual(failed.exception.code, "validation_failed")
            self.assertEqual(rollback_count, 1)

        with Session(self.engine) as session:
            run = session.get(WorkflowRun, draft.id)
            self.assertEqual(run.status, "validation_failed")
            self.assertEqual(
                session.scalars(
                    select(WorkflowEvent.event_type)
                    .where(WorkflowEvent.workflow_id == draft.id)
                    .order_by(WorkflowEvent.sequence)
                ).all(),
                ["draft_created", "validation_failed"],
            )

    def test_confirmation_rechecks_files_changed_after_full_validation(self):
        with Session(self.engine) as session:
            draft = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=valid_payload(),
            )
            file_row = session.scalar(
                select(WorkflowFile)
                .where(WorkflowFile.workflow_id == draft.id)
                .where(WorkflowFile.source_kind == "generated")
            )
            input_path = self.root / file_row.relative_path

        original_validate = workflow_service._validate_workflow

        def validate_then_tamper(active_session, root, run):
            original_validate(active_session, root, run)
            input_path.write_bytes(input_path.read_bytes() + b"tamper")

        with Session(self.engine) as session:
            with mock.patch.object(
                workflow_service,
                "_validate_workflow",
                side_effect=validate_then_tamper,
            ):
                with self.assertRaises(WorkflowServiceError) as failed:
                    confirm_workflow(
                        session,
                        self.root,
                        owner_id=self.owner_id,
                        workflow_id=draft.id,
                    )
            self.assertEqual(failed.exception.code, "validation_failed")

        with Session(self.engine) as session:
            run = session.get(WorkflowRun, draft.id)
            self.assertEqual(run.status, "validation_failed")
            self.assertEqual(
                session.scalars(
                    select(WorkflowEvent.event_type)
                    .where(WorkflowEvent.workflow_id == draft.id)
                    .order_by(WorkflowEvent.sequence)
                ).all(),
                ["draft_created", "validation_failed"],
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(WorkflowAttempt)), 0
            )

    def test_confirmation_rechecks_file_integrity_once_immediately_before_success(self):
        with Session(self.engine) as session:
            draft = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=valid_payload(),
            )

        calls = []
        original_validate = workflow_service._validate_workflow
        original_revalidate = workflow_service._revalidate_file_integrity
        original_transition = workflow_service._transition_workflow_status

        def record_validate(*args, **kwargs):
            calls.append("validate")
            return original_validate(*args, **kwargs)

        def record_revalidate(*args, **kwargs):
            calls.append("revalidate")
            return original_revalidate(*args, **kwargs)

        def record_transition(*args, **kwargs):
            calls.append(f"transition:{kwargs['target_status']}")
            return original_transition(*args, **kwargs)

        with Session(self.engine) as session:
            with mock.patch.object(
                workflow_service,
                "_validate_workflow",
                side_effect=record_validate,
            ), mock.patch.object(
                workflow_service,
                "_revalidate_file_integrity",
                side_effect=record_revalidate,
            ), mock.patch.object(
                workflow_service,
                "_transition_workflow_status",
                side_effect=record_transition,
            ):
                result = confirm_workflow(
                    session,
                    self.root,
                    owner_id=self.owner_id,
                    workflow_id=draft.id,
                )

        self.assertEqual(result.status, "validated")
        self.assertEqual(
            calls,
            [
                "transition:validating",
                "validate",
                "revalidate",
                "transition:validated",
            ],
        )

    def test_confirmation_claims_before_validation_without_releasing_the_transaction(self):
        with Session(self.engine) as session:
            draft = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=valid_payload(),
            )

        with Session(self.engine) as session:
            self.assertEqual(session.get(WorkflowRun, draft.id).status, "draft")
            original_validate = workflow_service._validate_workflow
            observed = []

            def assert_claimed(active_session, root, run):
                observed.append((run.status, active_session.in_transaction()))
                self.assertEqual(run.status, "validating")
                self.assertTrue(active_session.in_transaction())
                original_validate(active_session, root, run)

            with mock.patch.object(session, "rollback", wraps=session.rollback) as rollback:
                with mock.patch.object(
                    workflow_service,
                    "_validate_workflow",
                    side_effect=assert_claimed,
                ):
                    result = confirm_workflow(
                        session,
                        self.root,
                        owner_id=self.owner_id,
                        workflow_id=draft.id,
                    )

            self.assertEqual(result.status, "validated")
            self.assertEqual(observed, [("validating", True)])
            self.assertEqual(rollback.call_count, 1)

    def test_confirmation_write_lock_covers_step_and_template_validation(self):
        with Session(self.engine) as session:
            draft = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=valid_payload(),
            )

        original_validate = workflow_service._validate_workflow

        def assert_competing_writes_are_locked(active_session, root, run):
            statements = (
                update(WorkflowStep)
                .where(WorkflowStep.workflow_id == run.id)
                .values(status="contender"),
                update(WorkflowTemplate)
                .where(
                    WorkflowTemplate.template_key == "mos2",
                    WorkflowTemplate.version == run.template_version,
                )
                .values(definition_json={"tampered": True}),
            )
            for statement in statements:
                with self.engine.connect() as connection:
                    connection.exec_driver_sql("PRAGMA busy_timeout=0")
                    with self.assertRaises(OperationalError):
                        connection.execute(statement)
                    connection.rollback()
            original_validate(active_session, root, run)

        with Session(self.engine) as session:
            with mock.patch.object(
                workflow_service,
                "_validate_workflow",
                side_effect=assert_competing_writes_are_locked,
            ):
                result = confirm_workflow(
                    session,
                    self.root,
                    owner_id=self.owner_id,
                    workflow_id=draft.id,
                )

        self.assertEqual(result.status, "validated")

    def test_internal_confirmation_error_rolls_back_claim_for_retry(self):
        with Session(self.engine) as session:
            draft = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=valid_payload(),
            )

        with Session(self.engine) as session:
            with mock.patch.object(
                workflow_service,
                "_validate_workflow",
                side_effect=RuntimeError("internal failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "internal failure"):
                    confirm_workflow(
                        session,
                        self.root,
                        owner_id=self.owner_id,
                        workflow_id=draft.id,
                    )

        with Session(self.engine) as session:
            run = session.get(WorkflowRun, draft.id)
            self.assertEqual(run.status, "draft")
            self.assertEqual(
                session.scalars(
                    select(WorkflowEvent.event_type)
                    .where(WorkflowEvent.workflow_id == draft.id)
                    .order_by(WorkflowEvent.sequence)
                ).all(),
                ["draft_created"],
            )

    def test_confirmation_records_failure_for_tampered_or_missing_input(self):
        for failure_kind in ("tampered", "missing"):
            with self.subTest(failure_kind=failure_kind):
                with Session(self.engine) as session:
                    draft = create_draft(
                        session,
                        self.root,
                        owner_id=self.owner_id,
                        payload=valid_payload(),
                    )
                    file_row = session.scalar(
                        select(WorkflowFile)
                        .where(WorkflowFile.workflow_id == draft.id)
                        .where(WorkflowFile.source_kind == "generated")
                    )
                    input_path = self.root / file_row.relative_path
                if failure_kind == "tampered":
                    input_path.write_bytes(input_path.read_bytes() + b"tamper")
                else:
                    input_path.unlink()

                with Session(self.engine) as session:
                    with self.assertRaises(WorkflowServiceError) as failed:
                        confirm_workflow(
                            session,
                            self.root,
                            owner_id=self.owner_id,
                            workflow_id=draft.id,
                        )
                    self.assertEqual(failed.exception.code, "validation_failed")

                with Session(self.engine) as session:
                    run = session.get(WorkflowRun, draft.id)
                    self.assertEqual(run.status, "validation_failed")
                    self.assertEqual(
                        session.scalars(
                            select(WorkflowEvent.event_type)
                            .where(WorkflowEvent.workflow_id == draft.id)
                            .order_by(WorkflowEvent.sequence)
                        ).all(),
                        ["draft_created", "validation_failed"],
                    )
                    self.assertEqual(session.scalar(select(func.count()).select_from(WorkflowAttempt)), 0)

    def test_confirmation_rejects_database_path_traversal_without_leaking_it(self):
        with Session(self.engine) as session:
            draft = create_draft(
                session,
                self.root,
                owner_id=self.owner_id,
                payload=valid_payload(),
            )
            file_row = session.scalar(
                select(WorkflowFile)
                .where(WorkflowFile.workflow_id == draft.id)
                .where(WorkflowFile.source_kind == "generated")
            )
            file_row.relative_path = "../outside/POSCAR"
            session.commit()

        with Session(self.engine) as session:
            with self.assertRaises(WorkflowServiceError) as failed:
                confirm_workflow(
                    session,
                    self.root,
                    owner_id=self.owner_id,
                    workflow_id=draft.id,
                )
            self.assertEqual(failed.exception.code, "validation_failed")
            self.assertNotIn("outside", str(failed.exception))

        with Session(self.engine) as session:
            run = session.get(WorkflowRun, draft.id)
            self.assertEqual(run.status, "validation_failed")
            event_row = session.scalar(
                select(WorkflowEvent).where(
                    WorkflowEvent.workflow_id == draft.id,
                    WorkflowEvent.event_type == "validation_failed",
                )
            )
            self.assertEqual(json.loads(event_row.payload_json)["reason_code"], "invalid_file")

    def test_service_has_no_scheduler_or_subprocess_dependency(self):
        source = (
            Path(__file__).parents[1] / "services" / "competition_workflows.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("from subprocess", source)
        for scheduler_token in ("sbatch", "squeue", "sacct", "scancel", "slurm_job_id"):
            self.assertNotIn(scheduler_token, source.lower())


if __name__ == "__main__":
    unittest.main()
