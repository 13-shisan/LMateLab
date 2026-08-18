from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import traceback
import unittest
import uuid
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from database import Base
from models import User
from models_workflow import WorkflowAttempt, WorkflowFile, WorkflowRun, WorkflowStep
from services import competition_vasp
from services.competition_vasp import (
    ATTEMPT_AWAITING_ACCEPTANCE,
    ATTEMPT_PREPARING,
    ATTEMPT_SCIENTIFIC_FAILED,
    DEFAULT_POTCAR_CONTRACT,
    FIXED_STAGE_ORDER,
    STEP_BLOCKED,
    STAGE_REQUIRED_OUTPUTS,
    PotcarContract,
    VaspPolicyError,
    prepare_attempt_inputs,
    validate_potcar,
)


class PotcarPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.potcar = (
            b"TITEL  = PAW_PBE Mo_sv 02Feb2006\n"
            b"TITEL  = PAW_PBE S 06Sep2000\n"
        )
        self.contract = PotcarContract(
            symbols=("Mo_sv", "S"),
            titles=("PAW_PBE Mo_sv", "PAW_PBE S"),
            source_sha256=("a" * 64, "b" * 64),
            combined_sha256=hashlib.sha256(self.potcar).hexdigest(),
            vaspkit_version="1.5.1",
        )

    def write(self, name: str, content: bytes) -> Path:
        path = self.root / name
        path.write_bytes(content)
        return path

    def write_valid_inputs(self) -> None:
        self.write("POTCAR.spec", b"Mo_sv\nS\n")
        self.write("POTCAR", self.potcar)
        self.write("vaspkit-version.txt", b"VASPKIT Standard Edition 1.5.1\n")
        self.write(
            "potcar-source-sha256.txt",
            f"{'a' * 64}  Mo_sv\n{'b' * 64}  S\n".encode(),
        )

    def assert_policy_error(self, code: str) -> VaspPolicyError:
        with self.assertRaises(VaspPolicyError) as raised:
            validate_potcar(self.root, contract=self.contract)
        self.assertEqual(code, raised.exception.code)
        return raised.exception

    def test_potcar_accepts_exact_spec_titles_and_hashes(self):
        self.write_valid_inputs()

        result = validate_potcar(self.root, contract=self.contract)

        self.assertEqual(self.contract.combined_sha256, result["sha256"])
        self.assertEqual(["PAW_PBE Mo_sv", "PAW_PBE S"], result["titles"])
        self.assertEqual(["Mo_sv", "S"], result["symbols"])
        self.assertEqual(["a" * 64, "b" * 64], result["source_sha256"])
        self.assertEqual("1.5.1", result["vaspkit_version"])
        self.assertEqual(len(self.potcar), result["size_bytes"])

    def test_fixed_stage_policy_has_only_the_approved_stages_and_outputs(self):
        self.assertEqual(("relax", "scf", "band", "dos"), FIXED_STAGE_ORDER)
        self.assertEqual(
            {
                "relax": ("OUTCAR", "vasprun.xml", "OSZICAR", "CONTCAR"),
                "scf": ("OUTCAR", "vasprun.xml", "CHGCAR", "WAVECAR"),
                "band": ("OUTCAR", "vasprun.xml", "EIGENVAL"),
                "dos": ("OUTCAR", "vasprun.xml", "DOSCAR"),
            },
            STAGE_REQUIRED_OUTPUTS,
        )
        self.assertEqual(("Mo_sv", "S"), DEFAULT_POTCAR_CONTRACT.symbols)
        self.assertEqual(("PAW_PBE Mo_sv", "PAW_PBE S"), DEFAULT_POTCAR_CONTRACT.titles)
        self.assertEqual(
            (
                "2731df97e41766cc617548c5a8267718fdef1f509ac6bafa01e745abea2bdfaa",
                "0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132",
            ),
            DEFAULT_POTCAR_CONTRACT.source_sha256,
        )
        self.assertEqual(
            "509d41b6c93c3d7495d976f7a04dcf3f6960cfc94f39f13a67d146a7ded33045",
            DEFAULT_POTCAR_CONTRACT.combined_sha256,
        )
        self.assertEqual("1.5.1", DEFAULT_POTCAR_CONTRACT.vaspkit_version)

    def test_fixed_stage_output_mapping_is_immutable(self):
        with self.assertRaises(TypeError):
            STAGE_REQUIRED_OUTPUTS["relax"] = ()

    def test_contract_owns_mutable_injected_sequences(self):
        symbols = ["Mo_sv", "S"]
        titles = ["PAW_PBE Mo_sv", "PAW_PBE S"]
        source_hashes = ["a" * 64, "b" * 64]
        contract = PotcarContract(
            symbols=symbols,
            titles=titles,
            source_sha256=source_hashes,
            combined_sha256=hashlib.sha256(self.potcar).hexdigest(),
            vaspkit_version="1.5.1",
        )
        symbols[0] = "changed"
        titles[0] = "changed"
        source_hashes[0] = "c" * 64

        self.assertEqual(("Mo_sv", "S"), contract.symbols)
        self.assertEqual(("PAW_PBE Mo_sv", "PAW_PBE S"), contract.titles)
        self.assertEqual(("a" * 64, "b" * 64), contract.source_sha256)

    def test_contract_rejects_string_and_non_sequence_fields(self):
        with self.assertRaises(ValueError):
            PotcarContract(
                symbols="Mo",
                titles=("PAW_PBE M", "PAW_PBE o"),
                source_sha256=("a" * 64, "b" * 64),
                combined_sha256=hashlib.sha256(self.potcar).hexdigest(),
                vaspkit_version="1.5.1",
            )
        with self.assertRaises(ValueError):
            PotcarContract(
                symbols=object(),
                titles=("PAW_PBE Mo_sv", "PAW_PBE S"),
                source_sha256=("a" * 64, "b" * 64),
                combined_sha256=hashlib.sha256(self.potcar).hexdigest(),
                vaspkit_version="1.5.1",
            )

    def test_potcar_uses_the_injected_contract_title_prefixes(self):
        potcar = b"TITEL = PAW_PBE C 08Apr2002\nTITEL = PAW_PBE X 08Apr2002\n"
        contract = PotcarContract(
            symbols=("C", "X"),
            titles=("PAW_PBE C", "PAW_PBE X"),
            source_sha256=("c" * 64, "d" * 64),
            combined_sha256=hashlib.sha256(potcar).hexdigest(),
            vaspkit_version="1.5.1",
        )
        self.write("POTCAR.spec", b"C\nX\n")
        self.write("POTCAR", potcar)
        self.write("vaspkit-version.txt", b"VASPKIT Standard Edition 1.5.1\n")
        self.write(
            "potcar-source-sha256.txt",
            f"{'c' * 64}  C\n{'d' * 64}  X\n".encode(),
        )

        result = validate_potcar(self.root, contract=contract)

        self.assertEqual(["PAW_PBE C", "PAW_PBE X"], result["titles"])

    def test_potcar_rejects_wrong_spec_order_or_content(self):
        self.write_valid_inputs()
        for content in (b"S\nMo_sv\n", b"Mo_sv\nS", b"Mo\nS\n"):
            with self.subTest(content=content):
                self.write("POTCAR.spec", content)
                self.assert_policy_error("potcar_spec_invalid")

    def test_potcar_rejects_wrong_missing_or_additional_titles(self):
        self.write_valid_inputs()
        for content in (
            b"TITEL  = PAW_PBE S 06Sep2000\nTITEL  = PAW_PBE Mo_sv 02Feb2006\n",
            b"TITEL  = PAW_PBE Mo_sv 02Feb2006\n",
            self.potcar + b"TITEL  = PAW_PBE S 06Sep2000\n",
        ):
            with self.subTest(content=content):
                self.write("POTCAR", content)
                self.assert_policy_error("potcar_titles_invalid")

    def test_potcar_rejects_changed_or_invalid_source_hash_evidence(self):
        self.write_valid_inputs()
        for content in (
            f"{'c' * 64}  Mo_sv\n{'b' * 64}  S\n".encode(),
            f"{'A' * 64}  Mo_sv\n{'b' * 64}  S\n".encode(),
            f"{'a' * 64}  S\n{'b' * 64}  Mo_sv\n".encode(),
        ):
            with self.subTest(content=content):
                self.write("potcar-source-sha256.txt", content)
                self.assert_policy_error("potcar_source_evidence_invalid")

    def test_potcar_rejects_changed_combined_hash(self):
        self.write_valid_inputs()
        self.write("POTCAR", self.potcar + b"# synthetic change\n")

        self.assert_policy_error("potcar_sha256_mismatch")

    def test_potcar_rejects_symlinked_potcar_and_metadata(self):
        self.write_valid_inputs()
        target = self.root / "target"
        target.write_bytes(self.potcar)
        try:
            (self.root / "POTCAR").unlink()
            os.symlink(target, self.root / "POTCAR")
        except OSError as error:
            self.skipTest(f"Windows cannot create test symlink: {error.winerror}")
        self.assert_policy_error("potcar_symlink")

        (self.root / "POTCAR").unlink()
        self.write_valid_inputs()
        metadata_target = self.root / "metadata-target"
        metadata_target.write_bytes(b"VASPKIT Standard Edition 1.5.1\n")
        (self.root / "vaspkit-version.txt").unlink()
        os.symlink(metadata_target, self.root / "vaspkit-version.txt")
        self.assert_policy_error("potcar_symlink")

    def test_potcar_rejects_empty_potcar(self):
        self.write_valid_inputs()
        self.write("POTCAR", b"")

        self.assert_policy_error("potcar_empty")

    def test_potcar_rejects_oversized_version_and_source_evidence(self):
        self.write_valid_inputs()
        self.write("vaspkit-version.txt", b"x" * 8193)
        self.assert_policy_error("potcar_metadata_too_large")

        self.write_valid_inputs()
        self.write("potcar-source-sha256.txt", b"x" * 8193)
        self.assert_policy_error("potcar_metadata_too_large")

    def test_potcar_rejects_wrong_vaspkit_version(self):
        self.write_valid_inputs()
        self.write("vaspkit-version.txt", b"VASPKIT Standard Edition 1.5.0\n")

        self.assert_policy_error("vaspkit_version_invalid")

    def test_potcar_accepts_one_anchored_vaspkit_banner_with_surrounding_output(self):
        self.write_valid_inputs()
        self.write(
            "vaspkit-version.txt",
            b"synthetic startup notice\nVASPKIT Standard Edition 1.5.1\nsynthetic footer\n",
        )

        result = validate_potcar(self.root, contract=self.contract)

        self.assertEqual("1.5.1", result["vaspkit_version"])

    def test_potcar_rejects_non_banner_or_multiple_vaspkit_identities(self):
        self.write_valid_inputs()
        for content in (
            b"NOTVASPKIT 1.5.1\n",
            b"VASPKIT Standard Edition 1.5.1 synthetic\n",
            b"VASPKIT Standard Edition 1.5.1\nVASPKIT Standard Edition 1.5.1\n",
        ):
            with self.subTest(content=content):
                self.write("vaspkit-version.txt", content)
                self.assert_policy_error("vaspkit_version_invalid")

    def test_potcar_rejects_non_regular_required_file(self):
        self.write_valid_inputs()
        (self.root / "POTCAR").unlink()
        (self.root / "POTCAR").mkdir()

        self.assert_policy_error("potcar_file_invalid")

    def test_potcar_rejects_a_non_directory_attempt_root(self):
        root_file = self.write("not-a-directory", b"synthetic")

        with self.assertRaises(VaspPolicyError) as raised:
            validate_potcar(root_file, contract=self.contract)

        self.assertEqual("attempt_directory_invalid", raised.exception.code)

    def test_potcar_errors_do_not_disclose_path_or_content(self):
        self.write_valid_inputs()
        secret = b"TOP-SECRET-POTCAR-CONTENT"
        self.write("POTCAR", secret)

        error = self.assert_policy_error("potcar_titles_invalid")

        self.assertNotIn(str(self.root), str(error))
        self.assertNotIn(secret.decode(), str(error))

    def test_low_level_oserror_cause_and_traceback_are_sanitized(self):
        self.write_valid_inputs()
        secret = "SYNTHETIC-PRIVATE-CONTENT"
        raw_error = OSError(f"{secret} at {self.root / 'POTCAR'}")
        original_os_open = os.open

        def fail_potcar_open(path, flags, *args, **kwargs):
            if Path(os.fspath(path)).name == "POTCAR":
                raise raw_error
            return original_os_open(path, flags, *args, **kwargs)

        with mock.patch("services.competition_vasp.os.open", side_effect=fail_potcar_open):
            with self.assertRaises(VaspPolicyError) as raised:
                validate_potcar(self.root, contract=self.contract)

        formatted = "".join(
            traceback.format_exception(
                type(raised.exception), raised.exception, raised.exception.__traceback__
            )
        )
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn(str(self.root), formatted)
        self.assertNotIn(secret, formatted)

    def test_required_file_replacement_after_path_check_keeps_opened_identity(self):
        self.write_valid_inputs()
        self.write("descriptor-replacement", b"replaced\n")
        original_os_open = os.open
        descriptor_swapped = False

        def race_descriptor_open(path, flags, *args, **kwargs):
            nonlocal descriptor_swapped
            if Path(os.fspath(path)).name != "POTCAR.spec" or descriptor_swapped:
                return original_os_open(path, flags, *args, **kwargs)

            directory_fd = kwargs.get("dir_fd")
            if directory_fd is None:
                os.replace(self.root / "descriptor-replacement", self.root / "POTCAR.spec")
                descriptor_swapped = True
                return original_os_open(path, flags, *args, **kwargs)

            descriptor = original_os_open(path, flags, *args, **kwargs)
            try:
                os.replace(
                    "descriptor-replacement",
                    "POTCAR.spec",
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            except BaseException:
                os.close(descriptor)
                raise
            descriptor_swapped = True
            return descriptor

        with mock.patch(
            "services.competition_vasp.os.open", side_effect=race_descriptor_open
        ):
            if competition_vasp._HAS_SECURE_DIR_FD:
                result = validate_potcar(self.root, contract=self.contract)
            else:
                with self.assertRaises(VaspPolicyError) as raised:
                    validate_potcar(self.root, contract=self.contract)

        self.assertTrue(descriptor_swapped)
        if competition_vasp._HAS_SECURE_DIR_FD:
            self.assertEqual(self.contract.combined_sha256, result["sha256"])
        else:
            self.assertEqual("potcar_file_changed", raised.exception.code)

    def test_required_file_open_flags_include_nonblocking_guard(self):
        self.write_valid_inputs()
        original_os_open = os.open
        actual_nonblock = getattr(os, "O_NONBLOCK", 0)
        required_nonblock = actual_nonblock or (1 << 29)
        evidence_flags = []

        def capture_open_flags(path, flags, *args, **kwargs):
            if Path(os.fspath(path)).name in {
                "POTCAR.spec",
                "POTCAR",
                "vaspkit-version.txt",
                "potcar-source-sha256.txt",
            }:
                evidence_flags.append(flags)
            delegated_flags = flags if actual_nonblock else flags & ~required_nonblock
            return original_os_open(path, delegated_flags, *args, **kwargs)

        with (
            mock.patch.object(
                competition_vasp, "_O_NONBLOCK", required_nonblock, create=True
            ),
            mock.patch(
                "services.competition_vasp.os.open", side_effect=capture_open_flags
            ),
        ):
            validate_potcar(self.root, contract=self.contract)

        self.assertEqual(4, len(evidence_flags))
        self.assertTrue(all(flags & required_nonblock for flags in evidence_flags))

    def test_additional_titles_are_rejected_before_unbounded_accumulation(self):
        self.write_valid_inputs()
        self.write(
            "POTCAR",
            self.potcar + b"".join(b"TITEL = PAW_PBE X 08Apr2002\n" for _ in range(100)),
        )

        with mock.patch(
            "services.competition_vasp._canonical_title",
            wraps=competition_vasp._canonical_title,
        ) as canonical_title:
            self.assert_policy_error("potcar_titles_invalid")

        self.assertEqual(len(self.contract.titles), canonical_title.call_count)

    def test_potcar_fstat_failure_is_sanitized(self):
        self.write_valid_inputs()
        raw_error = OSError(f"synthetic stat failure at {self.root}")
        original_fstat = os.fstat

        def fail_regular_fstat(descriptor):
            identity = original_fstat(descriptor)
            if stat.S_ISREG(identity.st_mode):
                raise raw_error
            return identity

        with mock.patch(
            "services.competition_vasp.os.fstat", side_effect=fail_regular_fstat
        ):
            error = self.assert_policy_error("potcar_file_invalid")

        self.assertNotIn(str(self.root), str(error))
        self.assertIsNone(error.__cause__)

    def test_contract_rejects_malformed_injected_values(self):
        with self.assertRaises(ValueError):
            PotcarContract(
                symbols=("Mo_sv",),
                titles=("PAW_PBE Mo_sv", "PAW_PBE S"),
                source_sha256=("a" * 64, "b" * 64),
                combined_sha256="c" * 64,
                vaspkit_version="1.5.1",
            )
        with self.assertRaises(ValueError):
            PotcarContract(
                symbols=("Mo_sv", "S"),
                titles=("PAW_PBE Mo_sv", "PAW_PBE S"),
                source_sha256=("a" * 64, "b" * 64),
                combined_sha256="C" * 64,
                vaspkit_version="1.5.1",
            )


class AttemptInputTests(unittest.TestCase):
    """Real workflow/file ledgers for immutable fixed-stage input preparation."""

    template_version = "mos2_v1"
    release_commit = "a" * 40
    stage5_files = ("INCAR", "KPOINTS", "POSCAR", "POTCAR.spec")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name) / "workflow-root"
        self.engine = create_engine(f"sqlite:///{Path(self.temp_dir.name) / 'workflow.sqlite'}")

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
            session.add(owner)
            session.flush()
            self.owner_id = owner.id
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
                session.add(
                    WorkflowFile(
                        id=str(uuid.uuid4()),
                        workflow_id=self.workflow_id,
                        attempt_id=attempt_id,
                        owner_id=self.owner_id,
                        relative_path=relative_path,
                        size_bytes=len(content),
                        sha256=hashlib.sha256(content).hexdigest(),
                        source_kind="attempt_output",
                        metadata_json=metadata
                        or {
                            "logical_path": filename,
                            "step_key": step_key,
                            "accepted": True,
                        },
                    )
                )
            session.commit()
            return attempt_id

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
        self.assert_policy_error("input_source_invalid", "relax")

    def test_rejects_nonregular_source(self):
        source = self.root / self._stage5_directory_id / "relax" / "INCAR"
        source.unlink()
        source.mkdir()
        self.assert_policy_error("input_source_invalid", "relax")

    def test_rejects_existing_target_content_and_destination_alias(self):
        attempt_id = self._target_attempt("relax")
        target = self.root / self.workflow_id / "attempts" / attempt_id
        target.mkdir(mode=0o700, parents=True)
        source = self.root / self._stage5_directory_id / "relax" / "INCAR"
        try:
            os.link(source, target / "INCAR")
        except OSError as error:
            self.skipTest(f"hardlink creation unavailable: {error}")
        with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
            prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
        self.assertEqual("input_recovery_invalid", raised.exception.code)

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
        with mock.patch("services.competition_vasp._publish_staging_directory", side_effect=OSError("synthetic")):
            with Session(self.engine) as session, self.assertRaises(OSError):
                prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
        self.assertFalse((self.root / self.workflow_id / "attempts" / attempt_id).exists())
        with Session(self.engine) as session:
            self.assertEqual([], list(session.scalars(select(WorkflowFile).where(WorkflowFile.attempt_id == attempt_id))))

    def test_preparing_retry_returns_identical_immutable_publication(self):
        prepared = self.prepare("relax")
        original = (prepared.directory / "INCAR").read_bytes()
        (self.root / self._stage5_directory_id / "relax" / "INCAR").write_bytes(b"later tamper")
        with Session(self.engine) as session:
            recovered = prepare_attempt_inputs(
                session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                step_key="relax", attempt_id=prepared.attempt_id, template_version=self.template_version,
                release_commit=self.release_commit,
            )
            rows = list(session.scalars(select(WorkflowFile).where(WorkflowFile.attempt_id == prepared.attempt_id)))
        self.assertEqual(prepared.directory, recovered.directory)
        self.assertEqual(original, (recovered.directory / "INCAR").read_bytes())
        self.assertEqual(4, len(rows))

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
            "services.competition_vasp._commit_prepared_rows",
            side_effect=RuntimeError("synthetic database failure"),
        ):
            with Session(self.engine) as session, self.assertRaises(VaspPolicyError) as raised:
                prepare_attempt_inputs(
                    session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                    step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                    release_commit=self.release_commit,
                )
        self.assertEqual("input_ledger_recovery_required", raised.exception.code)
        self.assertTrue((self.root / self.workflow_id / "attempts" / attempt_id).is_dir())
        journal = competition_vasp._recovery_journal_path(self.root, self.workflow_id, attempt_id)
        self.assertTrue(journal.is_file())
        with Session(self.engine) as session:
            self.assertEqual([], list(session.scalars(select(WorkflowFile).where(WorkflowFile.attempt_id == attempt_id))))

    def test_journal_recovers_exact_rows_without_recopying_published_evidence(self):
        attempt_id = self._target_attempt("relax")
        with mock.patch(
            "services.competition_vasp._commit_prepared_rows",
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
        self.assertFalse(competition_vasp._recovery_journal_path(self.root, self.workflow_id, attempt_id).exists())

    def test_committed_publication_with_stale_journal_cleans_up_idempotently(self):
        with mock.patch("services.competition_vasp._remove_recovery_journal", return_value=None):
            prepared = self.prepare("relax")
        journal = competition_vasp._recovery_journal_path(
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

    def test_tampered_or_missing_journal_fails_closed_when_ledger_is_absent(self):
        for journal_content in (b"not-json", None):
            with self.subTest(journal_content=journal_content):
                attempt_id = self._target_attempt("relax")
                with mock.patch(
                    "services.competition_vasp._commit_prepared_rows",
                    side_effect=RuntimeError("synthetic database failure"),
                ):
                    with Session(self.engine) as session, self.assertRaises(VaspPolicyError):
                        prepare_attempt_inputs(
                            session, self.root, owner_id=self.owner_id, workflow_id=self.workflow_id,
                            step_key="relax", attempt_id=attempt_id, template_version=self.template_version,
                            release_commit=self.release_commit,
                        )
                journal = competition_vasp._recovery_journal_path(self.root, self.workflow_id, attempt_id)
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


if __name__ == "__main__":
    unittest.main()
