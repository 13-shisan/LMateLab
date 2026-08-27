from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from database import Base
from models import User
from models_workflow import WorkflowAttempt, WorkflowFile, WorkflowRun, WorkflowStep
from services import competition_attempt_inputs
from services.competition_attempt_inputs import (
    ATTEMPT_AWAITING_ACCEPTANCE,
    ATTEMPT_PREPARING,
    ATTEMPT_SCIENTIFIC_FAILED,
    STEP_BLOCKED,
    prepare_attempt_inputs,
)
from services.competition_vasp import FIXED_STAGE_ORDER, VaspPolicyError

class AttemptInputTests(unittest.TestCase):
    """Real workflow/file ledgers for immutable fixed-stage input preparation."""

    template_version = "mos2_v1"
    release_commit = "a" * 40
    stage5_files = ("INCAR", "KPOINTS", "POSCAR", "POTCAR.spec")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name) / "workflow-root"
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 'workflow.sqlite'}",
            poolclass=NullPool,
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        with Session(self.engine) as session:
            owner = User(
                email="operator@example.com",
                password_hash="hash",
                name="Operator",
                alias="",
                role="operator",
            )
            other_owner = User(
                email="other@example.com",
                password_hash="hash",
                name="Other",
                alias="",
                role="operator",
            )
            session.add_all((owner, other_owner))
            session.flush()
            self.owner_id = owner.id
            self.other_owner_id = other_owner.id
            self.workflow_id = str(uuid.uuid4())
            session.add(
                WorkflowRun(
                    id=self.workflow_id,
                    owner_id=self.owner_id,
                    template_version=self.template_version,
                    material="MoS2",
                    source_kind="builtin",
                    status="running",
                    release_commit=self.release_commit,
                    metadata_json={},
                )
            )
            for position, step_key in enumerate(FIXED_STAGE_ORDER):
                session.add(
                    WorkflowStep(
                        workflow_id=self.workflow_id,
                        step_key=step_key,
                        position=position,
                        status="waiting",
                        parameters_json={},
                    )
                )
            session.commit()
        self._stage5_directory_id = str(uuid.uuid4())
        self._seed_stage5_rows()

    def _step(self, session, step_key):
        return session.scalar(
            select(WorkflowStep).where(
                WorkflowStep.workflow_id == self.workflow_id,
                WorkflowStep.step_key == step_key,
            )
        )

    def _write_private(self, relative_path, content):
        path = self.root.joinpath(*relative_path.split("/"))
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        path.write_bytes(content)
        path.chmod(0o600)
        return path

    def _seed_stage5_rows(self):
        with Session(self.engine) as session:
            for step_key in FIXED_STAGE_ORDER:
                for filename in self.stage5_files:
                    relative_path = f"{self._stage5_directory_id}/{step_key}/{filename}"
                    content = f"stage5:{step_key}:{filename}".encode("ascii")
                    self._write_private(relative_path, content)
                    session.add(
                        WorkflowFile(
                            id=str(uuid.uuid4()),
                            workflow_id=self.workflow_id,
                            owner_id=self.owner_id,
                            relative_path=relative_path,
                            size_bytes=len(content),
                            sha256=hashlib.sha256(content).hexdigest(),
                            source_kind="generated",
                            metadata_json={
                                "logical_path": f"{step_key}/{filename}",
                                "step_key": step_key,
                            },
                        )
                    )
            session.commit()

    def _switch_to_generic_ws2_band_inputs(self):
        policy = b'{"generator":"vaspkit","task":302,"version":1}\n'
        with Session(self.engine) as session:
            run = session.get(WorkflowRun, self.workflow_id)
            run.template_version = "pbe_2d_v1"
            run.material = "WS2"
            run.source_kind = "upload"
            band_kpoints = self._file_with_logical_path(session, "band/KPOINTS")
            (self.root / band_kpoints.relative_path).unlink()
            session.delete(band_kpoints)
            relative_path = (
                f"{self._stage5_directory_id}/band/BAND_PATH.policy"
            )
            self._write_private(relative_path, policy)
            session.add(
                WorkflowFile(
                    id=str(uuid.uuid4()),
                    workflow_id=self.workflow_id,
                    owner_id=self.owner_id,
                    relative_path=relative_path,
                    size_bytes=len(policy),
                    sha256=hashlib.sha256(policy).hexdigest(),
                    source_kind="generated",
                    metadata_json={
                        "logical_path": "band/BAND_PATH.policy",
                        "step_key": "band",
                    },
                )
            )
            session.commit()
        self.template_version = "pbe_2d_v1"

    def _target_attempt(self, step_key):
        with Session(self.engine) as session:
            step = self._step(session, step_key)
            attempt_number = int(session.scalar(
                select(func.max(WorkflowAttempt.attempt_number)).where(WorkflowAttempt.step_id == step.id)
            ) or 0) + 1
            attempt = WorkflowAttempt(
                id=str(uuid.uuid4()),
                step_id=step.id,
                attempt_number=attempt_number,
                status=ATTEMPT_PREPARING,
                metadata_json={},
            )
            session.add(attempt)
            session.commit()
            return attempt.id

    def _parent_attempt(self, step_key, outputs, *, status="succeeded", metadata=None):
        with Session(self.engine) as session:
            step = self._step(session, step_key)
            step.status = "succeeded"
            attempt_number = int(session.scalar(
                select(func.max(WorkflowAttempt.attempt_number)).where(WorkflowAttempt.step_id == step.id)
            ) or 0) + 1
            attempt_id = str(uuid.uuid4())
            session.add(
                WorkflowAttempt(
                    id=attempt_id,
                    step_id=step.id,
                    attempt_number=attempt_number,
                    status=status,
                    metadata_json={},
                )
            )
            for filename, content in outputs.items():
                relative_path = f"{self.workflow_id}/attempts/{attempt_id}/{filename}"
                self._write_private(relative_path, content)
                source_kind = (
                    "attempt_input"
                    if step_key == "scf" and filename == "POSCAR"
                    else "attempt_output"
                )
                default_metadata = {
                    "logical_path": filename,
                    "step_key": step_key,
                }
                if source_kind == "attempt_output":
                    default_metadata["accepted"] = True
                session.add(
                    WorkflowFile(
                        id=str(uuid.uuid4()),
                        workflow_id=self.workflow_id,
                        attempt_id=attempt_id,
                        owner_id=self.owner_id,
                        relative_path=relative_path,
                        size_bytes=len(content),
                        sha256=hashlib.sha256(content).hexdigest(),
                        source_kind=source_kind,
                        metadata_json=metadata or default_metadata,
                    )
                )
            session.commit()
            return attempt_id

    def _accept_attempt_with_outputs(self, attempt_id, step_key, outputs):
        with Session(self.engine) as session:
            step = self._step(session, step_key)
            attempt = session.get(WorkflowAttempt, attempt_id)
            step.status = "succeeded"
            attempt.status = "succeeded"
            for filename, content in outputs.items():
                relative_path = f"{self.workflow_id}/attempts/{attempt_id}/{filename}"
                self._write_private(relative_path, content)
                session.add(WorkflowFile(
                    id=str(uuid.uuid4()),
                    workflow_id=self.workflow_id,
                    attempt_id=attempt_id,
                    owner_id=self.owner_id,
                    relative_path=relative_path,
                    size_bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    source_kind="attempt_output",
                    metadata_json={
                        "logical_path": filename,
                        "step_key": step_key,
                        "accepted": True,
                    },
                ))
            session.commit()

    def prepare(self, step_key, *, parent_outputs=None):
        attempt_id = self._target_attempt(step_key)
        if parent_outputs is not None:
            parent_step = "relax" if step_key == "scf" else "scf"
            self._parent_attempt(parent_step, parent_outputs)
        with Session(self.engine) as session:
            return prepare_attempt_inputs(
                session,
                self.root,
                owner_id=self.owner_id,
                workflow_id=self.workflow_id,
                step_key=step_key,
                attempt_id=attempt_id,
                template_version=self.template_version,
                release_commit=self.release_commit,
            )

    def assert_policy_error(self, code, step_key, **kwargs):
        with self.assertRaises(VaspPolicyError) as raised:
            self.prepare(step_key, **kwargs)
        self.assertEqual(code, raised.exception.code)

    def _file_with_logical_path(self, session, logical_path):
        for row in session.scalars(select(WorkflowFile).where(WorkflowFile.workflow_id == self.workflow_id)):
            metadata = row.metadata_json
            if not isinstance(metadata, dict):
                metadata = json.loads(metadata)
            if metadata.get("logical_path") == logical_path:
                return row
        self.fail(f"missing ledger row for {logical_path}")

    def _rewrite_journal_field(self, journal, field, value):
        envelope = json.loads(journal.read_bytes())
        envelope["payload"][field] = value
        envelope["sha256"] = hashlib.sha256(
            competition_attempt_inputs._canonical_json_bytes(envelope["payload"])
        ).hexdigest()
        rewritten = competition_attempt_inputs._canonical_json_bytes(envelope)
        journal.write_bytes(rewritten)
        return rewritten

    def test_status_constants_are_explicit_stage7_values(self):
        self.assertEqual("preparing", ATTEMPT_PREPARING)
        self.assertEqual("awaiting_acceptance", ATTEMPT_AWAITING_ACCEPTANCE)
        self.assertEqual("scientific_failed", ATTEMPT_SCIENTIFIC_FAILED)
        self.assertEqual("blocked", STEP_BLOCKED)

    def test_attempt_inputs_follow_fixed_parent_products(self):
        relax = self.prepare("relax")
        self.assertEqual({"INCAR", "KPOINTS", "POSCAR", "POTCAR.spec"}, relax.names)

        scf = self.prepare("scf", parent_outputs={"CONTCAR": b"relaxed"})
        self.assertEqual(b"relaxed", (scf.directory / "POSCAR").read_bytes())

        band = self.prepare(
            "band",
            parent_outputs={"POSCAR": b"scf-poscar", "CHGCAR": b"charge", "WAVECAR": b"wave"},
        )
        self.assertEqual(b"scf-poscar", (band.directory / "POSCAR").read_bytes())
        self.assertEqual(b"charge", (band.directory / "CHGCAR").read_bytes())
        self.assertFalse((band.directory / "WAVECAR").exists())

    def test_dos_copies_only_scf_poscar_and_charge(self):
        prepared = self.prepare(
            "dos",
            parent_outputs={"POSCAR": b"scf-poscar", "CHGCAR": b"charge", "WAVECAR": b"wave"},
        )

        self.assertEqual({"INCAR", "KPOINTS", "POTCAR.spec", "POSCAR", "CHGCAR"}, prepared.names)
        self.assertFalse((prepared.directory / "WAVECAR").exists())

    def test_generic_band_uses_302_policy_and_inherits_final_scf_inputs(self):
        self._switch_to_generic_ws2_band_inputs()

        prepared = self.prepare(
            "band",
            parent_outputs={
                "POSCAR": b"final-relaxed-ws2",
                "CHGCAR": b"ws2-charge",
                "WAVECAR": b"ignored-wave",
            },
        )

        self.assertEqual(
            {"INCAR", "BAND_PATH.policy", "POTCAR.spec", "POSCAR", "CHGCAR"},
            prepared.names,
        )
        self.assertEqual(
            b'{"generator":"vaspkit","task":302,"version":1}\n',
            (prepared.directory / "BAND_PATH.policy").read_bytes(),
        )
        self.assertEqual(
            b"final-relaxed-ws2", (prepared.directory / "POSCAR").read_bytes()
        )
        self.assertEqual(b"ws2-charge", (prepared.directory / "CHGCAR").read_bytes())
        self.assertFalse((prepared.directory / "KPOINTS").exists())
        self.assertFalse((prepared.directory / "WAVECAR").exists())

    def test_band_and_dos_follow_real_scf_input_and_output_lineage(self):
        relax_id = self._target_attempt("relax")
        with Session(self.engine) as session:
            prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=relax_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self._accept_attempt_with_outputs(relax_id, "relax", {"CONTCAR": b"relaxed-poscar"})

        scf_id = self._target_attempt("scf")
        with Session(self.engine) as session:
            prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="scf", attempt_id=scf_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
            scf_poscar = session.scalar(select(WorkflowFile).where(
                WorkflowFile.attempt_id == scf_id,
                WorkflowFile.source_kind == "attempt_input",
                WorkflowFile.relative_path.endswith("/POSCAR"),
            ))
        self._accept_attempt_with_outputs(
            scf_id,
            "scf",
            {"CHGCAR": b"scf-charge", "WAVECAR": b"ignored-wave"},
        )
        with Session(self.engine) as session:
            scf_chgcar = session.scalar(select(WorkflowFile).where(
                WorkflowFile.attempt_id == scf_id,
                WorkflowFile.source_kind == "attempt_output",
                WorkflowFile.relative_path.endswith("/CHGCAR"),
            ))

        for step_key in ("band", "dos"):
            attempt_id = self._target_attempt(step_key)
            with Session(self.engine) as session:
                prepared = prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key=step_key, attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
                rows = list(session.scalars(select(WorkflowFile).where(
                    WorkflowFile.attempt_id == attempt_id
                )))
            self.assertEqual(b"relaxed-poscar", (prepared.directory / "POSCAR").read_bytes())
            self.assertEqual(b"scf-charge", (prepared.directory / "CHGCAR").read_bytes())
            self.assertFalse((prepared.directory / "WAVECAR").exists())
            lineage = {
                (row.metadata_json if isinstance(row.metadata_json, dict) else json.loads(row.metadata_json))["logical_path"]:
                    (row.metadata_json if isinstance(row.metadata_json, dict) else json.loads(row.metadata_json))
                for row in rows
            }
            self.assertEqual(scf_poscar.id, lineage["POSCAR"]["source_file_id"])
            self.assertEqual(scf_chgcar.id, lineage["CHGCAR"]["source_file_id"])
            self.assertEqual(scf_id, lineage["POSCAR"]["source_attempt_id"])
            self.assertEqual(scf_id, lineage["CHGCAR"]["source_attempt_id"])
            with Session(self.engine) as session:
                recovered = prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key=step_key, attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
            self.assertEqual(prepared.directory, recovered.directory)

    def test_band_and_dos_reject_parent_outputs_mixed_across_attempts(self):
        for step_key in ("band", "dos"):
            with self.subTest(step_key=step_key):
                attempt_id = self._target_attempt(step_key)
                parent_ids = (
                    self._parent_attempt("scf", {"POSCAR": b"attempt-one-poscar"}),
                    self._parent_attempt("scf", {"CHGCAR": b"attempt-two-charge"}),
                )
                try:
                    with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                        prepare_attempt_inputs(
                            session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                            step_key=step_key, attempt_id=attempt_id, template_version=self.template_version,
                            release_commit=self.release_commit,
                        )
                    self.assertEqual("parent_lineage_invalid", raised.exception.code)
                finally:
                    for parent_id in parent_ids:
                        self._delete_parent(parent_id)

    def test_band_and_dos_reject_ambiguous_complete_parent_attempts(self):
        for step_key in ("band", "dos"):
            with self.subTest(step_key=step_key):
                attempt_id = self._target_attempt(step_key)
                parent_ids = (
                    self._parent_attempt("scf", {"POSCAR": b"first-poscar", "CHGCAR": b"first-charge"}),
                    self._parent_attempt("scf", {"POSCAR": b"second-poscar", "CHGCAR": b"second-charge"}),
                )
                try:
                    with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                        prepare_attempt_inputs(
                            session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                            step_key=step_key, attempt_id=attempt_id, template_version=self.template_version,
                            release_commit=self.release_commit,
                        )
                    self.assertEqual("parent_lineage_invalid", raised.exception.code)
                finally:
                    for parent_id in parent_ids:
                        self._delete_parent(parent_id)

    def test_rejects_tampered_stage5_or_parent_bytes(self):
        stage5_path = self.root / self._stage5_directory_id / "relax" / "INCAR"
        stage5_path.write_bytes(b"tampered")
        self.assert_policy_error("input_source_integrity", "relax")

        with Session(self.engine) as session:
            step = self._step(session, "scf")
            attempt_number = int(session.scalar(
                select(func.max(WorkflowAttempt.attempt_number)).where(WorkflowAttempt.step_id == step.id)
            ) or 0) + 1
            attempt = WorkflowAttempt(
                id=str(uuid.uuid4()), step_id=step.id, attempt_number=attempt_number,
                status=ATTEMPT_PREPARING, metadata_json={},
            )
            session.add(attempt)
            session.commit()
            attempt_id = attempt.id
        parent_id = self._parent_attempt("relax", {"CONTCAR": b"good"})
        (self.root / self.workflow_id / "attempts" / parent_id / "CONTCAR").write_bytes(b"tampered")
        with Session(self.engine) as session:
            with self.assertRaises(VaspPolicyError) as raised:
                prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key="scf", attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
        self.assertEqual("input_source_integrity", raised.exception.code)

    def test_rejects_source_symlink_or_nonregular_file(self):
        source = self.root / self._stage5_directory_id / "relax" / "INCAR"
        target = source.with_name("INCAR-target")
        target.write_bytes(source.read_bytes())
        source.unlink()
        try:
            os.symlink(target, source)
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        self.assert_policy_error("input_path_invalid", "relax")

    def test_rejects_nonregular_source(self):
        source = self.root / self._stage5_directory_id / "relax" / "INCAR"
        source.unlink()
        source.mkdir()
        self.assert_policy_error("input_source_invalid", "relax")

    def test_rejects_hardlink_at_actual_exclusive_destination_creation_path(self):
        attempt_id = self._target_attempt("relax")
        original_copy = competition_attempt_inputs.copy_verified_input
        injected = False

        def inject_hardlink(*args, **kwargs):
            nonlocal injected
            if not injected:
                os.link(kwargs["source"], kwargs["destination"])
                injected = True
            return original_copy(*args, **kwargs)

        with mock.patch(
            "services.competition_attempt_inputs.copy_verified_input",
            side_effect=inject_hardlink,
        ):
            with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
        )
        self.assertTrue(injected)
        self.assertEqual("input_destination_exists", raised.exception.code)
        with Session(self.engine) as session:
            recovered = prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self.assertTrue(recovered.directory.is_dir())

    def test_rejects_unexpected_parent_step_attempt_or_acceptance_status(self):
        for metadata, status, expected in (
            ({"logical_path": "CONTCAR", "step_key": "band", "accepted": True}, "succeeded", "parent_lineage_invalid"),
            ({"logical_path": "CONTCAR", "step_key": "relax", "accepted": True}, "awaiting_acceptance", "parent_not_accepted"),
            ({"logical_path": "CONTCAR", "step_key": "relax", "accepted": False}, "succeeded", "parent_lineage_invalid"),
        ):
            with self.subTest(metadata=metadata, status=status):
                parent_id = self._parent_attempt("relax", {"CONTCAR": b"relaxed"}, status=status, metadata=metadata)
                attempt_id = self._target_attempt("scf")
                with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                    prepare_attempt_inputs(
                        session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                        step_key="scf", attempt_id=attempt_id, template_version=self.template_version,
                        release_commit=self.release_commit,
                    )
                self.assertEqual(expected, raised.exception.code)
                self._delete_parent(parent_id)

    def _delete_parent(self, attempt_id):
        with Session(self.engine) as session:
            attempt = session.get(WorkflowAttempt, attempt_id)
            session.delete(attempt)
            session.commit()

    def test_rejects_missing_duplicate_or_unsafe_generated_rows(self):
        with Session(self.engine) as session:
            row = self._file_with_logical_path(session, "relax/KPOINTS")
            session.delete(row)
            session.commit()
        self.assert_policy_error("stage5_inputs_invalid", "relax")

        restored = b"stage5:relax:KPOINTS"
        restored_path = f"{self._stage5_directory_id}/relax/KPOINTS"
        self._write_private(restored_path, restored)
        with Session(self.engine) as session:
            session.add(WorkflowFile(
                id=str(uuid.uuid4()), workflow_id=self.workflow_id, owner_id=self.owner_id,
                relative_path=restored_path, size_bytes=len(restored),
                sha256=hashlib.sha256(restored).hexdigest(), source_kind="generated",
                metadata_json={"logical_path": "relax/KPOINTS", "step_key": "relax"},
            ))
            session.commit()
            content = b"duplicate"
            relative_path = f"{self._stage5_directory_id}/duplicate-INCAR"
            self._write_private(relative_path, content)
            session.add(WorkflowFile(
                id=str(uuid.uuid4()), workflow_id=self.workflow_id, owner_id=self.owner_id,
                relative_path=relative_path, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                source_kind="generated", metadata_json={"logical_path": "relax/INCAR", "step_key": "relax"},
            ))
            session.commit()
        self.assert_policy_error("stage5_inputs_invalid", "relax")

    def test_stage5_relative_path_unique_constraint_rejects_duplicate_evidence(self):
        with Session(self.engine) as session:
            original = self._file_with_logical_path(session, "relax/INCAR")
            session.add(WorkflowFile(
                id=str(uuid.uuid4()), workflow_id=self.workflow_id, owner_id=self.owner_id,
                relative_path=original.relative_path, size_bytes=original.size_bytes,
                sha256=original.sha256, source_kind="generated",
                metadata_json={"logical_path": "relax/INCAR-copy", "step_key": "relax"},
            ))
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()

    def test_rejects_foreign_owned_or_attempt_attached_stage5_rows(self):
        for mutation in ("owner", "attempt"):
            with self.subTest(mutation=mutation):
                with Session(self.engine) as session:
                    row = self._file_with_logical_path(session, "relax/INCAR")
                    if mutation == "owner":
                        row.owner_id = self.other_owner_id
                    else:
                        row.attempt_id = self._target_attempt("relax")
                    session.commit()
                self.assert_policy_error("stage5_inputs_invalid", "relax")
                with Session(self.engine) as session:
                    row = self._file_with_logical_path(session, "relax/INCAR")
                    row.owner_id = self.owner_id
                    row.attempt_id = None
                    session.commit()

    def test_existing_publication_rejects_mutated_lineage_without_touching_evidence(self):
        for field, value in (
            ("input_role", "tampered_role"),
            ("source_file_id", str(uuid.uuid4())),
            ("source_sha256", "0" * 64),
            ("logical_path", "tampered"),
            ("step_key", "scf"),
            ("relative_path", "tampered/path/INCAR"),
        ):
            with self.subTest(field=field):
                prepared = self.prepare("relax")
                original = (prepared.directory / "INCAR").read_bytes()
                with Session(self.engine) as session:
                    row = session.scalar(select(WorkflowFile).where(WorkflowFile.attempt_id == prepared.attempt_id))
                    if field == "relative_path":
                        row.relative_path = value
                    else:
                        metadata = (
                            dict(row.metadata_json)
                            if isinstance(row.metadata_json, dict)
                            else json.loads(row.metadata_json)
                        )
                        metadata[field] = value
                        row.metadata_json = metadata
                    session.commit()
                with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                    prepare_attempt_inputs(
                        session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                        step_key="relax", attempt_id=prepared.attempt_id, template_version=self.template_version,
                        release_commit=self.release_commit,
                    )
                self.assertEqual("input_publication_mismatch", raised.exception.code)
                self.assertEqual(original, (prepared.directory / "INCAR").read_bytes())

    def test_crash_before_publish_retry_rebuilds_cleanly(self):
        attempt_id = self._target_attempt("relax")
        with mock.patch("services.competition_attempt_inputs._publish_staging_directory", side_effect=OSError("synthetic")):
            with Session(self.engine) as session, self.assertRaises(OSError):
                prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
        target = self.root / self.workflow_id / "attempts" / attempt_id
        self.assertFalse(target.exists())
        with Session(self.engine) as session:
            self.assertEqual([], list(session.scalars(select(WorkflowFile).where(WorkflowFile.attempt_id == attempt_id))))
            prepared = prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self.assertEqual(target, prepared.directory)

    def test_rejects_traversing_or_absolute_database_relative_path(self):
        for relative_path in ("../outside", "/absolute", "C:\\outside"):
            with self.subTest(relative_path=relative_path):
                with Session(self.engine) as session:
                    row = session.scalar(select(WorkflowFile).where(WorkflowFile.relative_path == f"{self._stage5_directory_id}/relax/INCAR"))
                    row.relative_path = relative_path
                    session.commit()
                self.assert_policy_error("input_path_invalid", "relax")
                with Session(self.engine) as session:
                    row = self._file_with_logical_path(session, "relax/INCAR")
                    row.relative_path = f"{self._stage5_directory_id}/relax/INCAR"
                    session.commit()

    def test_crash_before_publish_leaves_no_attempt_directory_or_file_rows(self):
        attempt_id = self._target_attempt("relax")
        with mock.patch("services.competition_attempt_inputs._publish_staging_directory", side_effect=OSError("synthetic")):
            with Session(self.engine) as session, self.assertRaises(OSError):
                prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
        self.assertFalse((self.root / self.workflow_id / "attempts" / attempt_id).exists())
        with Session(self.engine) as session:
            self.assertEqual([], list(session.scalars(select(WorkflowFile).where(WorkflowFile.attempt_id == attempt_id))))

    def test_preparing_retry_revalidates_source_without_touching_publication(self):
        prepared = self.prepare("relax")
        original = (prepared.directory / "INCAR").read_bytes()
        (self.root / self._stage5_directory_id / "relax" / "INCAR").write_bytes(b"later tamper")
        with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
            prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=prepared.attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self.assertEqual("input_source_integrity", raised.exception.code)
        self.assertEqual(original, (prepared.directory / "INCAR").read_bytes())

    def test_copied_bytes_hashes_and_modes_are_private_and_independent(self):
        prepared = self.prepare("band", parent_outputs={"POSCAR": b"poscar", "CHGCAR": b"charge"})
        self.assertEqual(5, len(prepared.file_rows))
        for row in prepared.file_rows:
            path = self.root.joinpath(*row.relative_path.split("/"))
            self.assertEqual(row.sha256, hashlib.sha256(path.read_bytes()).hexdigest())
            if os.name != "nt":
                self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(1, path.stat().st_nlink)
        if os.name != "nt":
            self.assertEqual(0o700, stat.S_IMODE(prepared.directory.stat().st_mode))

    def test_commit_failure_after_publish_retains_journal_for_recovery(self):
        attempt_id = self._target_attempt("relax")
        with mock.patch(
            "services.competition_attempt_inputs._commit_prepared_rows",
            side_effect=RuntimeError("synthetic database failure"),
        ):
            with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
        self.assertEqual("input_ledger_recovery_required", raised.exception.code)
        target = self.root / self.workflow_id / "attempts" / attempt_id
        self.assertTrue(target.is_dir())
        if os.name != "nt":
            self.assertEqual(0o700, stat.S_IMODE(target.stat().st_mode))
        journal = competition_attempt_inputs._recovery_journal_path(self.root, self.workflow_id, attempt_id)
        self.assertTrue(journal.is_file())
        with Session(self.engine) as session:
            self.assertEqual([], list(session.scalars(select(WorkflowFile).where(WorkflowFile.attempt_id == attempt_id))))

    def test_post_rename_failure_cannot_destroy_journal_recovery(self):
        attempt_id = self._target_attempt("relax")
        target = self.root / self.workflow_id / "attempts" / attempt_id
        journal = competition_attempt_inputs._recovery_journal_path(
            self.root, self.workflow_id, attempt_id
        )
        original_chmod = Path.chmod

        def fail_target_chmod(path, mode, *args, **kwargs):
            if path == target and target.exists():
                raise OSError("synthetic post-rename mode failure")
            return original_chmod(path, mode, *args, **kwargs)

        with (
            mock.patch(
                "services.competition_attempt_inputs.Path.chmod",
                autospec=True,
                side_effect=fail_target_chmod,
            ),
            mock.patch(
                "services.competition_attempt_inputs._commit_prepared_rows",
                side_effect=RuntimeError("synthetic database failure"),
            ),
        ):
            with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
        self.assertEqual("input_ledger_recovery_required", raised.exception.code)
        self.assertTrue(target.is_dir())
        self.assertTrue(journal.is_file())
        with Session(self.engine) as session:
            recovered = prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self.assertEqual(target, recovered.directory)
        self.assertFalse(journal.exists())

    def test_journal_recovers_exact_rows_without_recopying_published_evidence(self):
        attempt_id = self._target_attempt("relax")
        with mock.patch(
            "services.competition_attempt_inputs._commit_prepared_rows",
            side_effect=RuntimeError("synthetic database failure"),
        ):
            with Session(self.engine) as session, self.assertRaises(VaspPolicyError):
                prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
        target = self.root / self.workflow_id / "attempts" / attempt_id
        original = (target / "INCAR").read_bytes()
        with Session(self.engine) as first:
            recovered = prepare_attempt_inputs(
                first, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        with Session(self.engine) as second:
            again = prepare_attempt_inputs(
                second, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
            rows = list(second.scalars(select(WorkflowFile).where(WorkflowFile.attempt_id == attempt_id)))
        self.assertEqual(target, recovered.directory)
        self.assertEqual(target, again.directory)
        self.assertEqual(original, (target / "INCAR").read_bytes())
        self.assertEqual(4, len(rows))
        self.assertFalse(competition_attempt_inputs._recovery_journal_path(self.root, self.workflow_id, attempt_id).exists())

    def test_committed_publication_with_stale_journal_cleans_up_idempotently(self):
        with mock.patch("services.competition_attempt_inputs._remove_recovery_journal", return_value=None):
            prepared = self.prepare("relax")
        journal = competition_attempt_inputs._recovery_journal_path(
            self.root, self.workflow_id, prepared.attempt_id
        )
        self.assertTrue(journal.exists())
        with Session(self.engine) as session:
            recovered = prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=prepared.attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self.assertEqual(prepared.directory, recovered.directory)
        self.assertFalse(journal.exists())

    def test_stale_journal_comparison_is_independent_of_persisted_row_order(self):
        with mock.patch("services.competition_attempt_inputs._remove_recovery_journal", return_value=None):
            prepared = self.prepare("relax")
        journal = competition_attempt_inputs._recovery_journal_path(
            self.root, self.workflow_id, prepared.attempt_id
        )
        reversed_result = []

        class ReverseFirstRowsSession(Session):
            def scalars(inner_self, statement, *args, **kwargs):
                result = super().scalars(statement, *args, **kwargs)
                if not reversed_result:
                    rows = list(result)
                    reversed_result.append(True)
                    return iter(reversed(rows))
                return result

        with ReverseFirstRowsSession(bind=self.engine) as session:
            recovered = prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=prepared.attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self.assertEqual([True], reversed_result)
        self.assertEqual(prepared.directory, recovered.directory)
        self.assertFalse(journal.exists())

    def test_stale_journal_comparison_rejects_mutated_persisted_row_id(self):
        with mock.patch("services.competition_attempt_inputs._remove_recovery_journal", return_value=None):
            prepared = self.prepare("relax")
        journal = competition_attempt_inputs._recovery_journal_path(
            self.root, self.workflow_id, prepared.attempt_id
        )
        original = (prepared.directory / "INCAR").read_bytes()
        with Session(self.engine) as session:
            row = session.scalar(select(WorkflowFile).where(
                WorkflowFile.attempt_id == prepared.attempt_id,
                WorkflowFile.relative_path.endswith("/INCAR"),
            ))
            row.id = str(uuid.uuid4())
            session.commit()
        with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
            prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=prepared.attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self.assertEqual("input_recovery_invalid", raised.exception.code)
        self.assertEqual(original, (prepared.directory / "INCAR").read_bytes())
        self.assertTrue(journal.exists())

    def test_tampered_or_missing_journal_fails_closed_when_ledger_is_absent(self):
        for journal_content in (b"not-json", None):
            with self.subTest(journal_content=journal_content):
                attempt_id = self._target_attempt("relax")
                with mock.patch(
                    "services.competition_attempt_inputs._commit_prepared_rows",
                    side_effect=RuntimeError("synthetic database failure"),
                ):
                    with Session(self.engine) as session, self.assertRaises(VaspPolicyError):
                        prepare_attempt_inputs(
                            session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                            step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                            release_commit=self.release_commit,
                        )
                journal = competition_attempt_inputs._recovery_journal_path(self.root, self.workflow_id, attempt_id)
                if journal_content is None:
                    journal.unlink()
                else:
                    journal.write_bytes(journal_content)
                with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                    prepare_attempt_inputs(
                        session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                        step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                        release_commit=self.release_commit,
                    )
                self.assertEqual("input_recovery_invalid", raised.exception.code)

    def test_recovery_rejects_rehashed_wrong_scope_journal(self):
        for field, value in (
            ("step_key", "scf"),
            ("template_version", "other_template"),
            ("release_commit", "b" * 40),
        ):
            with self.subTest(field=field):
                attempt_id = self._target_attempt("relax")
                with mock.patch(
                    "services.competition_attempt_inputs._commit_prepared_rows",
                    side_effect=RuntimeError("synthetic database failure"),
                ):
                    with Session(self.engine) as session, self.assertRaises(VaspPolicyError):
                        prepare_attempt_inputs(
                            session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                            step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                            release_commit=self.release_commit,
                        )
                target = self.root / self.workflow_id / "attempts" / attempt_id
                original = (target / "INCAR").read_bytes()
                journal = competition_attempt_inputs._recovery_journal_path(self.root, self.workflow_id, attempt_id)
                rewritten = self._rewrite_journal_field(journal, field, value)
                with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                    prepare_attempt_inputs(
                        session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                        step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                        release_commit=self.release_commit,
                    )
                self.assertEqual("input_recovery_invalid", raised.exception.code)
                with Session(self.engine) as session:
                    rows = list(session.scalars(select(WorkflowFile).where(
                        WorkflowFile.attempt_id == attempt_id
                    )))
                self.assertEqual([], rows)
                self.assertEqual(original, (target / "INCAR").read_bytes())
                self.assertEqual(rewritten, journal.read_bytes())

    def test_wrong_scope_journal_cannot_authorize_orphan_staging_cleanup(self):
        attempt_id = self._target_attempt("relax")
        staging = competition_attempt_inputs._new_staging_directory(self.root, self.workflow_id, attempt_id)
        competition_attempt_inputs._make_private_directory(staging)
        journal = competition_attempt_inputs._recovery_journal_path(self.root, self.workflow_id, attempt_id)
        payload = competition_attempt_inputs._journal_payload(
            workflow_id=self.workflow_id,
            attempt_id=attempt_id,
            step_key="relax",
            template_version=self.template_version,
            release_commit=self.release_commit,
            staging=staging,
            root=self.root,
            rows=(),
        )
        competition_attempt_inputs._write_recovery_journal(journal, payload)
        rewritten = self._rewrite_journal_field(journal, "step_key", "scf")
        with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
            prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self.assertEqual("input_recovery_invalid", raised.exception.code)
        self.assertTrue(staging.is_dir())
        self.assertEqual(rewritten, journal.read_bytes())

    def test_failed_unpublished_cleanup_retains_journal_when_staging_removal_fails(self):
        attempt_id = self._target_attempt("relax")
        journal = competition_attempt_inputs._recovery_journal_path(self.root, self.workflow_id, attempt_id)
        observed = {}

        def fail_copy(**_kwargs):
            raise VaspPolicyError("input_copy_mismatch", "synthetic copy policy failure")

        def fail_removal(staging):
            observed["staging"] = staging
            observed["journal"] = journal.read_bytes()
            raise OSError("synthetic staging removal failure")

        with (
            mock.patch("services.competition_attempt_inputs.copy_verified_input", side_effect=fail_copy),
            mock.patch("services.competition_attempt_inputs.shutil.rmtree", side_effect=fail_removal),
        ):
            with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
        self.assertEqual("input_copy_mismatch", raised.exception.code)
        self.assertTrue(observed["staging"].is_dir())
        self.assertEqual(observed["journal"], journal.read_bytes())

    def test_wrong_scope_journal_cannot_authorize_failed_unpublished_cleanup(self):
        attempt_id = self._target_attempt("relax")
        journal = competition_attempt_inputs._recovery_journal_path(self.root, self.workflow_id, attempt_id)
        observed = {}

        def rewrite_then_fail(**kwargs):
            observed["staging"] = kwargs["destination"].parent
            observed["journal"] = self._rewrite_journal_field(journal, "step_key", "scf")
            raise VaspPolicyError("input_copy_mismatch", "synthetic copy policy failure")

        with mock.patch(
            "services.competition_attempt_inputs.copy_verified_input",
            side_effect=rewrite_then_fail,
        ):
            with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
        self.assertEqual("input_copy_mismatch", raised.exception.code)
        self.assertTrue(observed["staging"].is_dir())
        self.assertEqual(observed["journal"], journal.read_bytes())

    def test_concurrent_prepare_is_rejected_while_first_writer_pauses_after_journal(self):
        attempt_id = self._target_attempt("relax")
        journal = competition_attempt_inputs._recovery_journal_path(self.root, self.workflow_id, attempt_id)
        entered = threading.Event()
        release = threading.Event()
        first_results = []
        first_errors = []
        original_write = competition_attempt_inputs._write_recovery_journal
        paused = False

        def pause_after_write(path, payload):
            nonlocal paused
            original_write(path, payload)
            if not paused:
                paused = True
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("test journal pause timed out")

        def first_prepare():
            worker_engine = create_engine(str(self.engine.url), poolclass=NullPool)
            try:
                with Session(worker_engine) as session:
                    first_results.append(prepare_attempt_inputs(
                        session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                        step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                        release_commit=self.release_commit,
                    ))
            except Exception as error:
                first_errors.append(error)
            finally:
                worker_engine.dispose()

        with mock.patch(
            "services.competition_attempt_inputs._write_recovery_journal",
            side_effect=pause_after_write,
        ):
            worker = threading.Thread(target=first_prepare)
            worker.start()
            self.assertTrue(entered.wait(5))
            journal_before = journal.read_bytes()
            staging_root = self.root / ".attempt-staging" / self.workflow_id
            staging_before = sorted(path.name for path in staging_root.iterdir())
            try:
                with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                    prepare_attempt_inputs(
                        session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                        step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                        release_commit=self.release_commit,
                    )
                self.assertEqual("attempt_preparation_in_progress", raised.exception.code)
                self.assertEqual(journal_before, journal.read_bytes())
                self.assertEqual(staging_before, sorted(path.name for path in staging_root.iterdir()))
                self.assertFalse((self.root / self.workflow_id / "attempts" / attempt_id).exists())
                with Session(self.engine) as check_session:
                    rows = list(check_session.scalars(select(WorkflowFile).where(
                        WorkflowFile.attempt_id == attempt_id
                    )))
                self.assertEqual([], rows)
            finally:
                release.set()
                worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual([], first_errors)
        self.assertEqual(1, len(first_results))
        with Session(self.engine) as session:
            recovered = prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self.assertEqual(first_results[0].directory, recovered.directory)

    def test_lock_directory_creation_race_returns_stable_in_progress_error(self):
        attempt_id = self._target_attempt("relax")
        locks_root = self.root / ".attempt-locks"
        original_make = competition_attempt_inputs._make_private_directory
        raced = False

        def lose_directory_creation_race(path):
            nonlocal raced
            if path == locks_root and not raced:
                raced = True
                original_make(path)
                raise FileExistsError
            original_make(path)

        with mock.patch(
            "services.competition_attempt_inputs._make_private_directory",
            side_effect=lose_directory_creation_race,
        ):
            try:
                with Session(self.engine) as session:
                    prepare_attempt_inputs(
                        session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                        step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                        release_commit=self.release_commit,
                    )
            except Exception as error:
                raised = error
            else:
                self.fail("directory creation race was not rejected")
        self.assertIsInstance(raised, VaspPolicyError)
        self.assertEqual("attempt_preparation_in_progress", raised.code)

    def test_concurrent_prepare_is_rejected_after_publish_before_commit(self):
        attempt_id = self._target_attempt("relax")
        target = self.root / self.workflow_id / "attempts" / attempt_id
        journal = competition_attempt_inputs._recovery_journal_path(self.root, self.workflow_id, attempt_id)
        entered = threading.Event()
        release = threading.Event()
        first_results = []
        first_errors = []
        original_commit = competition_attempt_inputs._commit_prepared_rows
        paused = False

        def pause_before_commit(session):
            nonlocal paused
            if not paused:
                paused = True
                entered.set()
                if not release.wait(10):
                    raise RuntimeError("test commit pause timed out")
            original_commit(session)

        def first_prepare():
            worker_engine = create_engine(str(self.engine.url), poolclass=NullPool)
            try:
                with Session(worker_engine) as session:
                    first_results.append(prepare_attempt_inputs(
                        session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                        step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                        release_commit=self.release_commit,
                    ))
            except Exception as error:
                first_errors.append(error)
            finally:
                worker_engine.dispose()

        with mock.patch(
            "services.competition_attempt_inputs._commit_prepared_rows",
            side_effect=pause_before_commit,
        ):
            worker = threading.Thread(target=first_prepare)
            worker.start()
            self.assertTrue(entered.wait(5))
            journal_before = journal.read_bytes()
            target_before = {path.name: path.read_bytes() for path in target.iterdir()}
            try:
                with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                    prepare_attempt_inputs(
                        session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                        step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                        release_commit=self.release_commit,
                    )
                self.assertEqual("attempt_preparation_in_progress", raised.exception.code)
                self.assertEqual(journal_before, journal.read_bytes())
                self.assertEqual(target_before, {path.name: path.read_bytes() for path in target.iterdir()})
                with Session(self.engine) as check_session:
                    rows = list(check_session.scalars(select(WorkflowFile).where(
                        WorkflowFile.attempt_id == attempt_id
                    )))
                self.assertEqual([], rows)
            finally:
                release.set()
                worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual([], first_errors)
        self.assertEqual(1, len(first_results))
        with Session(self.engine) as session:
            recovered = prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self.assertEqual(target, recovered.directory)


if __name__ == "__main__":
    unittest.main()
