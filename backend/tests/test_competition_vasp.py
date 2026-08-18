from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import stat
import tempfile
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pydantic import ValidationError

from schemas_workflow import DraftCreateRequest
from services import competition_vasp
from services.competition_vasp import (
    AcceptanceReport,
    DEFAULT_POTCAR_CONTRACT,
    FIXED_STAGE_ORDER,
    STAGE_REQUIRED_OUTPUTS,
    PotcarContract,
    VaspPolicyError,
    accept_vasp_attempt,
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

    def test_scf_nonconvergence_profile_is_fixed_and_not_public_input(self):
        original = (
            b"SYSTEM = MoS2 SCF\n"
            b"ENCUT = 520\n"
            b"EDIFF = 1E-7\n"
            b"NELM = 120\n"
            b"LWAVE = .TRUE.\n"
        )

        rendered = competition_vasp.render_acceptance_scf_incar(original)

        self.assertEqual(
            (
                b"SYSTEM = MoS2 SCF\n"
                b"ENCUT = 520\n"
                b"EDIFF = 1E-20\n"
                b"NELM = 1\n"
                b"LWAVE = .TRUE.\n"
            ),
            rendered,
        )
        self.assertNotEqual(hashlib.sha256(original).digest(), hashlib.sha256(rendered).digest())
        with self.assertRaises(ValidationError):
            DraftCreateRequest.model_validate(
                {
                    "template_version": "mos2_v1",
                    "source_kind": "builtin",
                    "steps": ["relax", "scf", "band", "dos"],
                    "parameters": {},
                    "acceptance_profile": "scf_nonconvergence_v1",
                }
            )

    def test_scf_nonconvergence_profile_rejects_ambiguous_or_unexpected_input(self):
        for content in (
            b"EDIFF = 1E-7\n",
            b"NELM = 120\n",
            b"EDIFF = 1E-7\nEDIFF = 1E-8\nNELM = 120\n",
            b"EDIFF = 1E-7\nNELM = 120\nNELM = 121\n",
            b"EDIFF = 1E-7\nNELM = 120\n\x00",
        ):
            with self.subTest(content=content):
                with self.assertRaises(VaspPolicyError) as raised:
                    competition_vasp.render_acceptance_scf_incar(content)
                self.assertEqual("acceptance_profile_input_invalid", raised.exception.code)

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


class ScientificAcceptanceTests(unittest.TestCase):
    band_kpoints = (
        b"MoS2 high-symmetry path\n40\nLine-mode\nReciprocal\n"
        b"0 0 0 ! G\n0.5 0 0 ! M\n\n"
        b"0.5 0 0 ! M\n0.333333333333333 0.333333333333333 0 ! K\n\n"
        b"0.333333333333333 0.333333333333333 0 ! K\n0 0 0 ! G\n"
    )
    dos_kpoints = b"Automatic mesh\n0\nGamma\n24 24 1\n0 0 0\n"

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
        path.chmod(0o600)
        return path

    def write_complete_outputs(self, stage: str) -> None:
        common = {
            "POTCAR.spec": b"Mo_sv\nS\n",
            "POTCAR": self.potcar,
            "potcar-source-sha256.txt": (
                f"{'a' * 64}  Mo_sv\n{'b' * 64}  S\n".encode("ascii")
            ),
            "vaspkit-version.txt": b"VASPKIT Standard Edition 1.5.1\n",
            "vasp-exit-code.txt": b"0\n",
            "runtime-time.txt": (
                b"Elapsed (wall clock) time (h:mm:ss or m:ss): 0:01.25\n"
                b"Maximum resident set size (kbytes): 123456\n"
            ),
            "OUTCAR": (
                b"vasp.6.4.2 28Jun24\n"
                b" General timing and accounting informations for this job:\n"
            ),
            "vasprun.xml": b"<?xml version='1.0'?><modeling></modeling>\n",
        }
        for name, content in common.items():
            self.write(name, content)
        for name in STAGE_REQUIRED_OUTPUTS[stage]:
            if not (self.root / name).exists():
                self.write(name, b"accepted-stage-evidence\n")
        if stage == "band":
            self.write("KPOINTS", self.band_kpoints)
        if stage == "dos":
            self.write("KPOINTS", self.dos_kpoints)
            self.write("INCAR", b"SYSTEM = MoS2 DOS\nNEDOS = 3000\n")

    @staticmethod
    def fake_vasprun(*, electronic=True, ionic=True, efermi=1.25, parameters=None):
        return SimpleNamespace(
            converged_electronic=electronic,
            converged_ionic=ionic,
            efermi=efermi,
            parameters=parameters or {},
        )

    @staticmethod
    def valid_artifact(name="OUTCAR", digest="a" * 64, size_bytes=1):
        return {"name": name, "sha256": digest, "size_bytes": size_bytes}

    def accept(self, stage: str, **kwargs):
        scheduler_state = kwargs.pop("scheduler_state", "COMPLETED")
        scheduler_exit_code = kwargs.pop("scheduler_exit_code", "0:0")
        vasprun_loader = kwargs.pop(
            "vasprun_loader",
            lambda _path: self.fake_vasprun(
                parameters={"NEDOS": 3000} if stage == "dos" else {}
            ),
        )
        structure_loader = kwargs.pop("structure_loader", lambda _path: object())
        return accept_vasp_attempt(
            self.root,
            stage,
            scheduler_state=scheduler_state,
            scheduler_exit_code=scheduler_exit_code,
            vasprun_loader=vasprun_loader,
            structure_loader=structure_loader,
            potcar_contract=self.contract,
            **kwargs,
        )

    def swap_attempt_directory_while_reading(
        self, loader_path: Path, filename: str, alternate_content: bytes
    ) -> bytes:
        held = self.root.with_name(self.root.name + "-held")
        alternate = self.root.with_name(self.root.name + "-alternate")
        alternate.mkdir(mode=0o700)
        alternate_file = alternate / filename
        alternate_file.write_bytes(alternate_content)
        alternate_file.chmod(0o600)
        os.replace(self.root, held)
        os.replace(alternate, self.root)
        try:
            return loader_path.read_bytes()
        finally:
            os.replace(self.root, alternate)
            os.replace(held, self.root)
            shutil.rmtree(alternate)

    def assert_rejected(self, code: str, stage: str = "scf", **kwargs):
        report = self.accept(stage, **kwargs)
        self.assertFalse(report.accepted)
        self.assertEqual(code, report.reason_code)
        self.assertTrue(report.checks)
        self.assertFalse(report.checks[-1]["passed"])
        return report

    def test_acceptance_report_is_deeply_immutable_and_as_dict_has_no_aliases(self):
        checks = [{"name": "scheduler_state", "passed": True}]
        measurements = {"vasp_version": "6.4.3"}
        artifacts = [{"name": "OUTCAR", "sha256": "a" * 64, "size_bytes": 1}]
        report = AcceptanceReport(True, None, checks, measurements, artifacts)
        checks[0]["name"] = "stage"
        measurements["vasp_version"] = "9.9.9"
        artifacts[0]["name"] = "changed"

        first = report.as_dict()
        first["checks"][0]["name"] = "stage"
        first["measurements"]["vasp_version"] = "9.9.9"
        first["artifacts"][0]["name"] = "changed"

        self.assertEqual(report.as_dict(), {
            "accepted": True,
            "reason_code": None,
            "checks": [{"name": "scheduler_state", "passed": True}],
            "measurements": {"vasp_version": "6.4.3"},
            "artifacts": [{"name": "OUTCAR", "sha256": "a" * 64, "size_bytes": 1}],
        })
        with self.assertRaises(TypeError):
            report.measurements["changed"] = True

    def test_acceptance_report_rejects_inconsistent_success_or_failure(self):
        for accepted, reason_code, checks in (
            (True, "failure", ({"name": "stage", "passed": False},)),
            (False, None, ({"name": "stage", "passed": False},)),
            (False, "failure", ()),
            (False, "failure", ({"name": "stage", "passed": True},)),
        ):
            with self.subTest(accepted=accepted, reason_code=reason_code, checks=checks):
                with self.assertRaises(ValueError):
                    AcceptanceReport(accepted, reason_code, checks, {}, ())

    def test_acceptance_report_reason_code_requires_builtin_string(self):
        class CustomReason(str):
            pass

        failed_checks = ({"name": "stage", "passed": False, "reason_code": "failure"},)
        with self.assertRaises(ValueError):
            AcceptanceReport(False, CustomReason("failure"), failed_checks, {}, ())

        accepted = AcceptanceReport(
            True,
            None,
            ({"name": "stage", "passed": True},),
            {},
            (self.valid_artifact(),),
        )
        self.assertTrue(accepted.accepted)
        self.assertIsNone(accepted.reason_code)

    def test_acceptance_report_reason_codes_are_bounded_stable_tokens(self):
        invalid_reason_codes = (
            "C:\\licensed\\POTCAR",
            "/licensed/POTCAR",
            "../POTCAR",
            "TITEL = PAW_PBE Mo_sv 02Feb2006",
            "Uppercase",
            "contains whitespace",
            "colon:content",
            "x" * 65,
        )
        for reason_code in invalid_reason_codes:
            with self.subTest(reason_code=reason_code):
                with self.assertRaises(ValueError):
                    AcceptanceReport(
                        False,
                        reason_code,
                        ({"name": "stage", "passed": False, "reason_code": reason_code},),
                        {},
                        (),
                    )

    def test_acceptance_report_validates_every_failed_check_reason_code(self):
        invalid_reason_codes = (
            "C:\\licensed\\POTCAR",
            "/licensed/POTCAR",
            "../POTCAR",
            "TITEL = PAW_PBE Mo_sv 02Feb2006",
        )
        for reason_code in invalid_reason_codes:
            with self.subTest(reason_code=reason_code):
                with self.assertRaises(ValueError):
                    AcceptanceReport(
                        False,
                        "first_failure",
                        (
                            {
                                "name": "stage",
                                "passed": False,
                                "reason_code": "first_failure",
                            },
                            {
                                "name": "scheduler_state",
                                "passed": False,
                                "reason_code": reason_code,
                            },
                        ),
                        {},
                        (),
                    )

    def test_acceptance_report_rejects_every_sensitive_string_carrier_repro(self):
        carrier_strings = (
            "../licensed/POTCAR",
            "C:licensed\\POTCAR",
            "\\licensed\\POTCAR",
            "file:///licensed/POTCAR",
            "PAW_PBE Mo_sv 02Feb2006 TITEL = licensed POTCAR body",
        )
        artifact = (self.valid_artifact("POTCAR"),)
        for sensitive in carrier_strings:
            for field in ("check", "measurement"):
                with self.subTest(sensitive=sensitive, field=field):
                    checks = (
                        {
                            "name": "artifact:POTCAR",
                            "passed": True,
                            **({"details": sensitive} if field == "check" else {}),
                        },
                    )
                    measurements = {
                        "vasp_version": sensitive if field == "measurement" else "6.4.3"
                    }
                    with self.assertRaises(ValueError):
                        AcceptanceReport(True, None, checks, measurements, artifact)

    def test_acceptance_report_check_schema_is_closed(self):
        malformed_checks = (
            ({"name": "stage", "passed": True, "details": "benign"},),
            ({"name": "stage", "passed": True, "extra": None},),
            (
                {
                    "name": "stage",
                    "passed": False,
                    "reason_code": "failure",
                    "details": "benign",
                },
            ),
        )
        for checks in malformed_checks:
            with self.subTest(checks=checks):
                accepted = checks[0]["passed"]
                reason_code = None if accepted else "failure"
                artifacts = (self.valid_artifact(),) if accepted else ()
                with self.assertRaises(ValueError):
                    AcceptanceReport(accepted, reason_code, checks, {}, artifacts)

    def test_acceptance_report_check_names_are_the_fixed_acceptance_vocabulary(self):
        fixed_names = {
            "stage",
            "scheduler_state",
            "scheduler_exit_code",
            "attempt_directory",
            "vasp_exit_code",
            "vaspkit_version",
            "potcar",
            "runtime_evidence",
            "outcar",
            "parser_snapshot",
            "vasprun",
            "electronic_convergence",
            "ionic_convergence",
            "contcar",
            "scf_efermi",
            "band_kpoints",
            "dos_kpoints",
            "dos_nedos",
            "evidence_stability",
        }
        artifact_names = set().union(
            *STAGE_REQUIRED_OUTPUTS.values(),
            {
                "vasp-exit-code.txt",
                "runtime-time.txt",
                "vaspkit-version.txt",
                "POTCAR.spec",
                "POTCAR",
                "potcar-source-sha256.txt",
                "KPOINTS",
                "INCAR",
            },
        )
        allowed_names = fixed_names | {f"artifact:{name}" for name in artifact_names}
        artifact = (self.valid_artifact(),)
        for name in allowed_names:
            with self.subTest(name=name):
                report = AcceptanceReport(
                    True, None, ({"name": name, "passed": True},), {}, artifact
                )
                self.assertEqual(name, report.checks[0]["name"])

        rejected_names = (
            "external",
            "../licensed/POTCAR",
            "C:licensed\\POTCAR",
            "\\licensed\\POTCAR",
            "file:///licensed/POTCAR",
            "artifact:external.dat",
            "artifact:../POTCAR",
        )
        for name in rejected_names:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    AcceptanceReport(
                        False,
                        "failure",
                        ({"name": name, "passed": False, "reason_code": "failure"},),
                        {},
                        (),
                    )

    def test_acceptance_report_measurement_schema_is_closed_and_flat(self):
        invalid_measurements = (
            {"unknown": 1},
            {"unknown": {"nested": "value"}},
            {"vasp_version": {"nested": "6.4.3"}},
            {"vasp_version": ["6.4.3"]},
        )
        for measurements in invalid_measurements:
            with self.subTest(measurements=measurements):
                with self.assertRaises(ValueError):
                    AcceptanceReport(
                        True,
                        None,
                        ({"name": "stage", "passed": True},),
                        measurements,
                        (self.valid_artifact(),),
                    )

    def test_acceptance_report_measurements_require_exact_types_and_safe_domains(self):
        class CustomInt(int):
            pass

        class CustomFloat(float):
            pass

        class CustomString(str):
            pass

        invalid_measurements = (
            {"vasp_exit_code": -1},
            {"vasp_exit_code": True},
            {"vasp_exit_code": 0.0},
            {"vasp_exit_code": CustomInt(0)},
            {"vaspkit_version": 151},
            {"vaspkit_version": "1.5"},
            {"vaspkit_version": "1.5.1 extra"},
            {"vaspkit_version": "\u0661.\u0665.\u0661"},
            {"vaspkit_version": CustomString("1.5.1")},
            {"elapsed_wall_seconds": -0.1},
            {"elapsed_wall_seconds": 0},
            {"elapsed_wall_seconds": True},
            {"elapsed_wall_seconds": math.nan},
            {"elapsed_wall_seconds": math.inf},
            {"elapsed_wall_seconds": CustomFloat(0.0)},
            {"process_tree_peak_rss_kbytes": -1},
            {"process_tree_peak_rss_kbytes": 1.0},
            {"process_tree_peak_rss_kbytes": True},
            {"process_tree_peak_rss_kbytes": CustomInt(0)},
            {"vasp_version": 643},
            {"vasp_version": "6.4"},
            {"vasp_version": "vasp.6.4.3"},
            {"vasp_version": CustomString("6.4.3")},
            {"efermi_ev": True},
            {"efermi_ev": "1.25"},
            {"efermi_ev": math.nan},
            {"efermi_ev": math.inf},
            {"efermi_ev": CustomFloat(1.25)},
            {"kpoints_sha256": "A" * 64},
            {"kpoints_sha256": "a" * 63},
            {"kpoints_sha256": 1},
            {"kpoints_sha256": CustomString("a" * 64)},
            {"nedos": 99},
            {"nedos": 10001},
            {"nedos": 100.0},
            {"nedos": True},
            {"nedos": CustomInt(100)},
        )
        for measurements in invalid_measurements:
            with self.subTest(measurements=measurements):
                with self.assertRaises(ValueError):
                    AcceptanceReport(
                        True,
                        None,
                        ({"name": "stage", "passed": True},),
                        measurements,
                        (self.valid_artifact(),),
                    )

        report = AcceptanceReport(
            True,
            None,
            ({"name": "stage", "passed": True},),
            {
                "vasp_exit_code": 17,
                "vaspkit_version": "1.5.1",
                "elapsed_wall_seconds": 0.0,
                "process_tree_peak_rss_kbytes": 0,
                "vasp_version": "6.4.2",
                "efermi_ev": -2,
                "kpoints_sha256": "a" * 64,
                "nedos": 10000,
            },
            (self.valid_artifact(),),
        )
        self.assertEqual(17, report.measurements["vasp_exit_code"])
        self.assertEqual(-2, report.measurements["efermi_ev"])

    def test_generated_reports_round_trip_through_the_closed_schema(self):
        reports = [
            self.accept("external"),
            self.accept("scf", scheduler_state="FAILED"),
        ]
        self.write_complete_outputs("scf")
        self.write("vasp-exit-code.txt", b"17\n")
        reports.append(self.accept("scf"))

        for stage in FIXED_STAGE_ORDER:
            self.write_complete_outputs(stage)
            reports.append(self.accept(stage))

        self.assertEqual({}, reports[0].as_dict()["measurements"])
        self.assertEqual({}, reports[1].as_dict()["measurements"])
        self.assertEqual(
            {"vasp_exit_code": 17}, reports[2].as_dict()["measurements"]
        )
        for report in reports:
            with self.subTest(report=report.as_dict()):
                payload = report.as_dict()
                reconstructed = AcceptanceReport(
                    payload["accepted"],
                    payload["reason_code"],
                    tuple(payload["checks"]),
                    payload["measurements"],
                    tuple(payload["artifacts"]),
                )
                self.assertEqual(payload, reconstructed.as_dict())

    def test_acceptance_report_rejects_values_outside_canonical_json_domain(self):
        class MutableBox:
            def __init__(self):
                self.value = "mutable"

        hostile_values = (
            {"mutable"},
            frozenset({"mutable"}),
            bytearray(b"mutable"),
            b"bytes",
            MutableBox(),
            {1: "non-string key"},
            {1: "collision", "1": "string key"},
            math.nan,
            math.inf,
            -math.inf,
        )
        for value in hostile_values:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ValueError):
                    AcceptanceReport(
                        True,
                        None,
                        ({"name": "stage", "passed": True},),
                        {"vasp_exit_code": value},
                        (self.valid_artifact(),),
                    )

    def test_acceptance_report_valid_domain_is_deterministic_json(self):
        measurements = {
            "vasp_version": "6.4.3",
            "vasp_exit_code": 0,
            "elapsed_wall_seconds": 1.5,
        }
        report = AcceptanceReport(
            True,
            None,
            ({"name": "stage", "passed": True},),
            measurements,
            (self.valid_artifact(),),
        )
        expected = report.as_dict()
        measurements["vasp_version"] = "9.9.9"

        self.assertEqual(expected, report.as_dict())
        self.assertEqual(
            json.dumps(expected, allow_nan=False, sort_keys=True),
            json.dumps(report.as_dict(), allow_nan=False, sort_keys=True),
        )

    def test_acceptance_report_enforces_canonical_check_schema(self):
        class CustomString(str):
            pass

        artifact = (self.valid_artifact(),)
        malformed = (
            (True, None, (), artifact),
            (True, None, ({"name": "", "passed": True},), artifact),
            (True, None, ({"name": CustomString("stage"), "passed": True},), artifact),
            (True, None, ({"name": 1, "passed": True},), artifact),
            (True, None, ({"name": "stage"},), artifact),
            (True, None, ({"name": "stage", "passed": 1},), artifact),
            (True, None, ({"name": "stage", "passed": True, "reason_code": "bad"},), artifact),
            (
                True,
                None,
                (
                    {"name": "stage", "passed": True},
                    {"name": "stage", "passed": True},
                ),
                artifact,
            ),
            (False, "failure", ({"name": "stage", "passed": False},), ()),
            (
                False,
                "failure",
                ({"name": "stage", "passed": False, "reason_code": ""},),
                (),
            ),
            (
                False,
                "failure",
                (
                    {
                        "name": "stage",
                        "passed": False,
                        "reason_code": CustomString("failure"),
                    },
                ),
                (),
            ),
            (
                False,
                "first",
                ({"name": "stage", "passed": False, "reason_code": "second"},),
                (),
            ),
        )
        for accepted, reason_code, checks, artifacts in malformed:
            with self.subTest(accepted=accepted, reason_code=reason_code, checks=checks):
                with self.assertRaises(ValueError):
                    AcceptanceReport(accepted, reason_code, checks, {}, artifacts)

        partial = AcceptanceReport(
            False,
            "failure",
            ({"name": "stage", "passed": False, "reason_code": "failure"},),
            {},
            (),
        )
        self.assertFalse(partial.accepted)

    def test_acceptance_report_enforces_canonical_artifact_schema_and_order(self):
        checks = ({"name": "stage", "passed": True},)
        malformed_artifacts = (
            (),
            ({"name": "", "sha256": "a" * 64, "size_bytes": 1},),
            ({"name": "../OUTCAR", "sha256": "a" * 64, "size_bytes": 1},),
            ({"name": "dir/OUTCAR", "sha256": "a" * 64, "size_bytes": 1},),
            ({"name": "dir\\OUTCAR", "sha256": "a" * 64, "size_bytes": 1},),
            ({"name": 1, "sha256": "a" * 64, "size_bytes": 1},),
            ({"name": "OUTCAR", "sha256": "A" * 64, "size_bytes": 1},),
            ({"name": "OUTCAR", "sha256": "a" * 63, "size_bytes": 1},),
            ({"name": "OUTCAR", "sha256": "a" * 64, "size_bytes": 0},),
            ({"name": "OUTCAR", "sha256": "a" * 64, "size_bytes": -1},),
            ({"name": "OUTCAR", "sha256": "a" * 64, "size_bytes": True},),
            (
                {"name": "OUTCAR", "sha256": "a" * 64, "size_bytes": 1, "extra": None},
            ),
            (self.valid_artifact(), self.valid_artifact()),
        )
        for artifacts in malformed_artifacts:
            with self.subTest(artifacts=artifacts):
                with self.assertRaises(ValueError):
                    AcceptanceReport(True, None, checks, {}, artifacts)

        report = AcceptanceReport(
            True,
            None,
            checks,
            {},
            (
                self.valid_artifact("vasprun.xml", "b" * 64, 2),
                self.valid_artifact("OUTCAR", "a" * 64, 1),
            ),
        )
        self.assertEqual(["OUTCAR", "vasprun.xml"], [item["name"] for item in report.artifacts])

    def test_acceptance_report_rejects_artifact_names_outside_fixed_vocabulary(self):
        checks = ({"name": "stage", "passed": True},)
        invalid_names = (
            "C:licensed",
            "file:secret",
            "TITEL = licensed POTCAR body",
            "secret.txt",
            "../OUTCAR",
            "dir/OUTCAR",
            "dir\\OUTCAR",
        )
        for name in invalid_names:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    AcceptanceReport(
                        True,
                        None,
                        checks,
                        {},
                        (self.valid_artifact(name),),
                    )

    def test_acceptance_report_accepts_every_fixed_artifact_name(self):
        artifact_names = competition_vasp._ACCEPTANCE_ARTIFACT_NAMES
        self.assertTrue(artifact_names)
        for name in sorted(artifact_names):
            with self.subTest(name=name):
                report = AcceptanceReport(
                    True,
                    None,
                    ({"name": f"artifact:{name}", "passed": True},),
                    {},
                    (self.valid_artifact(name),),
                )
                self.assertEqual(name, report.artifacts[0]["name"])

    def test_generated_success_and_failure_reports_use_fixed_artifact_names(self):
        allowed_names = competition_vasp._ACCEPTANCE_ARTIFACT_NAMES
        for stage in FIXED_STAGE_ORDER:
            with self.subTest(stage=stage):
                self.write_complete_outputs(stage)
                accepted = self.accept(stage)
                self.assertTrue(accepted.accepted, accepted.as_dict())

                self.write("vasp-exit-code.txt", b"1\n")
                rejected = self.accept(stage)
                self.assertFalse(rejected.accepted, rejected.as_dict())
                self.assertEqual("vasp_exit_nonzero", rejected.reason_code)

                for report in (accepted, rejected):
                    self.assertTrue(
                        {artifact["name"] for artifact in report.artifacts}
                        <= allowed_names
                    )

    def test_each_fixed_stage_accepts_complete_evidence_and_hashes_all_artifacts(self):
        for stage in FIXED_STAGE_ORDER:
            with self.subTest(stage=stage):
                self.write_complete_outputs(stage)
                report = self.accept(stage)
                self.assertTrue(report.accepted, report.as_dict())
                self.assertIsNone(report.reason_code)
                self.assertEqual("1.5.1", report.measurements["vaspkit_version"])
                self.assertEqual("6.4.2", report.measurements["vasp_version"])
                self.assertEqual(1.25, report.measurements["elapsed_wall_seconds"])
                self.assertEqual(123456, report.measurements["process_tree_peak_rss_kbytes"])
                self.assertNotIn("MaxRSS", json.dumps(report.as_dict()))
                self.assertNotIn("gpu", json.dumps(report.as_dict()).lower())
                artifact_names = {artifact["name"] for artifact in report.artifacts}
                self.assertTrue(set(STAGE_REQUIRED_OUTPUTS[stage]).issubset(artifact_names))
                self.assertTrue({"POTCAR", "vasp-exit-code.txt", "runtime-time.txt", "vaspkit-version.txt"}.issubset(artifact_names))
                for artifact in report.artifacts:
                    self.assertRegex(artifact["sha256"], r"^[0-9a-f]{64}$")
                    self.assertGreater(artifact["size_bytes"], 0)

    def test_scheduler_state_must_be_exactly_completed(self):
        self.write_complete_outputs("scf")
        for value in ("COMPLETING", "completed", "COMPLETED+"):
            with self.subTest(value=value):
                self.assert_rejected("scheduler_state_not_completed", scheduler_state=value)

    def test_scheduler_exit_code_must_be_exactly_zero_colon_zero(self):
        self.write_complete_outputs("scf")
        for value in ("1:0", "0:1", "0", " 0:0"):
            with self.subTest(value=value):
                self.assert_rejected("scheduler_exit_code_nonzero", scheduler_exit_code=value)

    def test_vasp_exit_evidence_must_be_one_integer_zero(self):
        self.write_complete_outputs("scf")
        for content, code in (
            (b"1\n", "vasp_exit_nonzero"),
            (b"zero\n", "vasp_exit_invalid"),
            (b"0\n0\n", "vasp_exit_invalid"),
            (b"+0\n", "vasp_exit_invalid"),
        ):
            with self.subTest(content=content):
                self.write("vasp-exit-code.txt", content)
                self.assert_rejected(code)

    def test_common_metadata_rejects_oversized_symlink_and_nonregular_evidence(self):
        for kind, code in (
            ("oversized", "evidence_too_large"),
            ("nonregular", "evidence_nonregular"),
        ):
            with self.subTest(kind=kind):
                self.write_complete_outputs("scf")
                path = self.root / "runtime-time.txt"
                path.unlink()
                if kind == "oversized":
                    self.write("runtime-time.txt", b"x" * 8193)
                else:
                    path.mkdir()
                self.assert_rejected(code)

    def test_metadata_symlink_is_rejected_before_open_without_os_symlink_privilege(self):
        self.write_complete_outputs("scf")
        target = self.root / "runtime-time.txt"
        original_lstat = Path.lstat

        def report_symlink(path):
            identity = original_lstat(path)
            if path != target:
                return identity
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777)

        with (
            mock.patch.object(Path, "lstat", autospec=True, side_effect=report_symlink),
            mock.patch.object(competition_vasp, "_HAS_SECURE_DIR_FD", False),
        ):
            self.assert_rejected("evidence_symlink")

    @unittest.skipIf(os.name == "nt", "POSIX mode bits are not authoritative on Windows")
    def test_evidence_must_be_private(self):
        self.write_complete_outputs("scf")
        (self.root / "runtime-time.txt").chmod(0o640)
        self.assert_rejected("evidence_not_private")

    def test_posix_private_mode_policy_rejects_group_or_world_access(self):
        with mock.patch.object(competition_vasp.os, "name", "posix"):
            self.assertTrue(competition_vasp._private_evidence_mode(
                SimpleNamespace(st_mode=stat.S_IFREG | 0o600)
            ))
            self.assertFalse(competition_vasp._private_evidence_mode(
                SimpleNamespace(st_mode=stat.S_IFREG | 0o640)
            ))
            self.assertFalse(competition_vasp._private_evidence_mode(
                SimpleNamespace(st_mode=stat.S_IFREG | 0o604)
            ))

    def test_required_artifacts_reject_missing_empty_symlink_and_nonregular_files(self):
        for kind, code in (
            ("missing", "evidence_missing"),
            ("empty", "evidence_empty"),
            ("nonregular", "evidence_nonregular"),
        ):
            with self.subTest(kind=kind):
                self.write_complete_outputs("scf")
                path = self.root / "CHGCAR"
                path.unlink()
                if kind == "empty":
                    self.write("CHGCAR", b"")
                elif kind == "nonregular":
                    path.mkdir()
                self.assert_rejected(code)

    def test_required_artifact_symlink_is_rejected_before_open_without_privilege(self):
        self.write_complete_outputs("scf")
        target = self.root / "CHGCAR"
        original_lstat = Path.lstat

        def report_symlink(path):
            identity = original_lstat(path)
            if path != target:
                return identity
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777)

        with (
            mock.patch.object(Path, "lstat", autospec=True, side_effect=report_symlink),
            mock.patch.object(competition_vasp, "_HAS_SECURE_DIR_FD", False),
        ):
            self.assert_rejected("evidence_symlink")

    def test_real_required_artifact_symlink_is_never_followed(self):
        self.write_complete_outputs("scf")
        path = self.root / "CHGCAR"
        path.unlink()
        target = self.write("chgcar-target", b"evidence\n")
        try:
            path.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"real symlinks unavailable: {exc}")

        self.assert_rejected("evidence_symlink")

    def test_required_artifact_is_rejected_above_fixed_output_bound(self):
        self.write_complete_outputs("scf")
        with (self.root / "CHGCAR").open("wb") as handle:
            handle.truncate(competition_vasp._MAX_ACCEPTANCE_OUTPUT_BYTES + 1)
        self.assert_rejected("evidence_too_large")

    def test_outcar_requires_exact_completion_marker(self):
        self.write_complete_outputs("scf")
        for content in (
            b"vasp.6.4.3 27Mar24\nGeneral timing and accounting information for this job:\n",
            b"vasp.6.4.3 27Mar24\ngeneral timing and accounting informations for this job:\n",
        ):
            with self.subTest(content=content):
                self.write("OUTCAR", content)
                self.assert_rejected("outcar_incomplete")

    def test_outcar_accepts_only_the_real_single_space_completion_line(self):
        real = b"vasp.6.4.2 28Jun24\n General timing and accounting informations for this job:\n"
        self.write_complete_outputs("scf")
        self.write("OUTCAR", real)
        report = self.accept("scf")
        self.assertTrue(report.accepted, report.as_dict())
        self.assertEqual("6.4.2", report.measurements["vasp_version"])

        for marker in (
            b"General timing and accounting informations for this job:",
            b"  General timing and accounting informations for this job:",
            b" General timing and accounting informations for this job: trailing",
        ):
            with self.subTest(marker=marker):
                self.write_complete_outputs("scf")
                self.write("OUTCAR", b"vasp.6.4.2 28Jun24\n" + marker + b"\n")
                self.assert_rejected("outcar_incomplete")

    def test_vasprun_must_be_complete_xml_and_pymatgen_parseable(self):
        self.write_complete_outputs("scf")
        self.write("vasprun.xml", b"<modeling><calculation>")
        self.assert_rejected("vasprun_unparseable")

        self.write_complete_outputs("scf")
        def reject_loader(_path):
            raise ValueError("synthetic parser detail")
        report = self.assert_rejected("vasprun_unparseable", vasprun_loader=reject_loader)
        self.assertNotIn("synthetic", json.dumps(report.as_dict()))

    def test_vasprun_uses_streaming_fixed_scope_snapshot(self):
        self.assertEqual(256 * 1024 * 1024, competition_vasp._MAX_VASPRUN_XML_BYTES)
        self.assertEqual(
            competition_vasp._MAX_VASPRUN_XML_BYTES,
            competition_vasp._acceptance_size_limit("vasprun.xml"),
        )
        self.assertLess(
            competition_vasp._acceptance_size_limit("vasprun.xml"),
            competition_vasp._acceptance_size_limit("WAVECAR"),
        )

        self.write_complete_outputs("scf")
        with mock.patch.object(
            competition_vasp.ElementTree,
            "parse",
            side_effect=AssertionError("full-tree XML parse is forbidden"),
        ), mock.patch.object(
            competition_vasp.ElementTree,
            "iterparse",
            wraps=competition_vasp.ElementTree.iterparse,
        ) as iterparse:
            report = self.accept("scf")
        self.assertTrue(report.accepted, report.as_dict())
        self.assertTrue(iterparse.called)

    def test_vasprun_xml_rejects_policy_oversize_before_reading(self):
        self.write_complete_outputs("scf")
        with (self.root / "vasprun.xml").open("wb") as handle:
            handle.truncate(256 * 1024 * 1024 + 1)
        self.assert_rejected("evidence_too_large")

    def test_streaming_xml_memory_error_is_sanitized(self):
        self.write_complete_outputs("scf")
        with mock.patch.object(
            competition_vasp.ElementTree, "iterparse", side_effect=MemoryError("raw")
        ):
            report = self.assert_rejected("vasprun_unparseable")
        self.assertNotIn("raw", json.dumps(report.as_dict()))

    def test_acceptance_parsers_receive_ephemeral_pinned_snapshots(self):
        self.write_complete_outputs("relax")
        original_xml = (self.root / "vasprun.xml").read_bytes()
        original_contcar = (self.root / "CONTCAR").read_bytes()
        observed = {}

        def vasprun_loader(path):
            observed["vasprun_path"] = path
            observed["vasprun_bytes"] = path.read_bytes()
            return self.fake_vasprun()

        def structure_loader(path):
            observed["contcar_path"] = path
            observed["contcar_bytes"] = path.read_bytes()
            return object()

        report = self.accept(
            "relax", vasprun_loader=vasprun_loader, structure_loader=structure_loader
        )
        self.assertTrue(report.accepted, report.as_dict())
        self.assertEqual(original_xml, observed["vasprun_bytes"])
        self.assertEqual(original_contcar, observed["contcar_bytes"])
        self.assertNotEqual(self.root, observed["vasprun_path"].parent)
        self.assertNotEqual(self.root, observed["contcar_path"].parent)
        self.assertFalse(observed["vasprun_path"].exists())
        self.assertFalse(observed["contcar_path"].exists())

    def test_vasprun_loader_rejects_in_place_snapshot_mutation(self):
        self.write_complete_outputs("scf")
        alternate = b"vasprun snapshot changed after hashing"

        def mutating_loader(path):
            path.write_bytes(alternate)
            return self.fake_vasprun()

        report = self.assert_rejected(
            "evidence_changed", "scf", vasprun_loader=mutating_loader
        )
        self.assertNotIn(alternate.decode("ascii"), json.dumps(report.as_dict()))

    def test_contcar_loader_rejects_in_place_snapshot_mutation(self):
        self.write_complete_outputs("relax")
        alternate = b"CONTCAR snapshot changed after hashing"

        def mutating_loader(path):
            path.write_bytes(alternate)
            return object()

        report = self.assert_rejected(
            "evidence_changed", "relax", structure_loader=mutating_loader
        )
        self.assertNotIn(alternate.decode("ascii"), json.dumps(report.as_dict()))

    def test_vasprun_loader_rejects_snapshot_path_replacement(self):
        self.write_complete_outputs("scf")
        alternate = b"replacement vasprun snapshot"

        def replacing_loader(path):
            replacement = path.with_name(path.name + ".replacement")
            replacement.write_bytes(alternate)
            replacement.chmod(0o600)
            os.replace(replacement, path)
            return self.fake_vasprun()

        report = self.accept("scf", vasprun_loader=replacing_loader)
        self.assertFalse(report.accepted)
        self.assertIn(report.reason_code, {"evidence_changed", "vasprun_unparseable"})
        self.assertEqual(report.reason_code, report.checks[-1]["reason_code"])
        self.assertNotIn(alternate.decode("ascii"), json.dumps(report.as_dict()))

    def test_contcar_loader_rejects_snapshot_path_replacement(self):
        self.write_complete_outputs("relax")
        alternate = b"replacement CONTCAR snapshot"

        def replacing_loader(path):
            replacement = path.with_name(path.name + ".replacement")
            replacement.write_bytes(alternate)
            replacement.chmod(0o600)
            os.replace(replacement, path)
            return object()

        report = self.assert_rejected(
            "evidence_changed", "relax", structure_loader=replacing_loader
        )
        self.assertNotIn(alternate.decode("ascii"), json.dumps(report.as_dict()))

    @unittest.skipIf(os.name == "nt", "POSIX snapshot replacement required")
    def test_vasprun_loader_rejects_snapshot_swap_restore(self):
        self.write_complete_outputs("scf")
        alternate = b"swap-restore vasprun snapshot"

        def swapping_loader(path):
            held = path.with_name(path.name + ".held")
            replacement = path.with_name(path.name + ".replacement")
            replacement.write_bytes(alternate)
            replacement.chmod(0o600)
            os.replace(path, held)
            os.replace(replacement, path)
            try:
                self.assertEqual(alternate, path.read_bytes())
            finally:
                os.replace(path, replacement)
                os.replace(held, path)
                replacement.unlink()
            return self.fake_vasprun()

        report = self.assert_rejected(
            "evidence_changed", "scf", vasprun_loader=swapping_loader
        )
        self.assertNotIn(alternate.decode("ascii"), json.dumps(report.as_dict()))

    @unittest.skipIf(os.name == "nt", "POSIX snapshot replacement required")
    def test_contcar_loader_rejects_snapshot_swap_restore(self):
        self.write_complete_outputs("relax")
        alternate = b"swap-restore CONTCAR snapshot"

        def swapping_loader(path):
            held = path.with_name(path.name + ".held")
            replacement = path.with_name(path.name + ".replacement")
            replacement.write_bytes(alternate)
            replacement.chmod(0o600)
            os.replace(path, held)
            os.replace(replacement, path)
            try:
                self.assertEqual(alternate, path.read_bytes())
            finally:
                os.replace(path, replacement)
                os.replace(held, path)
                replacement.unlink()
            return object()

        report = self.assert_rejected(
            "evidence_changed", "relax", structure_loader=swapping_loader
        )
        self.assertNotIn(alternate.decode("ascii"), json.dumps(report.as_dict()))

    @unittest.skipIf(os.name == "nt", "POSIX directory replacement required")
    def test_vasprun_loader_is_anchored_during_attempt_directory_swap_restore(self):
        self.write_complete_outputs("scf")
        original = (self.root / "vasprun.xml").read_bytes()
        observed = {}

        def swapping_loader(path):
            observed["path"] = path
            observed["bytes"] = self.swap_attempt_directory_while_reading(
                path, "vasprun.xml", b"<modeling><alternate/></modeling>\n"
            )
            return self.fake_vasprun()

        report = self.accept("scf", vasprun_loader=swapping_loader)
        self.assertTrue(report.accepted, report.as_dict())
        self.assertEqual(original, observed["bytes"])
        self.assertNotEqual(self.root, observed["path"].parent)
        self.assertFalse(observed["path"].exists())

    @unittest.skipIf(os.name == "nt", "POSIX directory replacement required")
    def test_contcar_loader_is_anchored_during_attempt_directory_swap_restore(self):
        self.write_complete_outputs("relax")
        original = (self.root / "CONTCAR").read_bytes()
        observed = {}

        def swapping_loader(path):
            observed["path"] = path
            observed["bytes"] = self.swap_attempt_directory_while_reading(
                path, "CONTCAR", b"alternate structure\n"
            )
            return object()

        report = self.accept("relax", structure_loader=swapping_loader)
        self.assertTrue(report.accepted, report.as_dict())
        self.assertEqual(original, observed["bytes"])
        self.assertNotEqual(self.root, observed["path"].parent)
        self.assertFalse(observed["path"].exists())

    def test_acceptance_does_not_reopen_potcar_policy_paths(self):
        self.write_complete_outputs("scf")
        with mock.patch.object(
            competition_vasp,
            "validate_potcar",
            side_effect=AssertionError("acceptance must use pinned POTCAR descriptors"),
        ):
            report = self.accept("scf")
        self.assertTrue(report.accepted, report.as_dict())

    def test_scf_rejects_slurm_success_when_electronic_convergence_is_false(self):
        self.write_complete_outputs("scf")

        report = self.accept(
            "scf",
            vasprun_loader=lambda _path: self.fake_vasprun(electronic=False),
        )

        self.assertIsInstance(report, AcceptanceReport)
        self.assertFalse(report.accepted)
        self.assertEqual("electronic_not_converged", report.reason_code)

    def test_relax_requires_ionic_convergence(self):
        self.write_complete_outputs("relax")
        self.assert_rejected(
            "ionic_not_converged",
            "relax",
            vasprun_loader=lambda _path: self.fake_vasprun(ionic=False),
        )

    def test_scf_fermi_level_must_be_finite_real_number(self):
        self.write_complete_outputs("scf")
        for value in (math.nan, math.inf, -math.inf, "1.25", True, None):
            with self.subTest(value=value):
                self.assert_rejected(
                    "scf_efermi_invalid",
                    vasprun_loader=lambda _path, value=value: self.fake_vasprun(efermi=value),
                )

    def test_band_requires_exact_fixed_kpoints_hash_and_path(self):
        self.write_complete_outputs("band")
        for content in (
            self.band_kpoints.replace(b"40\n", b"39\n", 1),
            self.band_kpoints.replace(b"0.5 0 0 ! M", b"0.4 0 0 ! M", 1),
            self.band_kpoints.replace(b"Line-mode", b"line-mode"),
        ):
            with self.subTest(digest=hashlib.sha256(content).hexdigest()):
                self.write("KPOINTS", content)
                self.assert_rejected("band_kpoints_invalid", "band")

    def test_dos_requires_exact_fixed_gamma_mesh_hash(self):
        self.write_complete_outputs("dos")
        for content in (
            self.dos_kpoints.replace(b"24 24 1", b"24 24 2"),
            self.dos_kpoints.replace(b"Gamma", b"Monkhorst-Pack"),
        ):
            with self.subTest(content=content):
                self.write("KPOINTS", content)
                self.assert_rejected("dos_kpoints_invalid", "dos")

    def test_dos_nedos_is_bounded_unambiguous_and_matches_effective_parameter(self):
        for incar, parameter, code in (
            (b"NEDOS = 99\n", 99, "dos_nedos_invalid"),
            (b"NEDOS = 10001\n", 10001, "dos_nedos_invalid"),
            (b"NEDOS = 3000\nNEDOS = 3000\n", 3000, "dos_nedos_invalid"),
            (b"NEDOS = three thousand\n", 3000, "dos_nedos_invalid"),
            (b"NEDOS = 4000\n", 3000, "dos_nedos_mismatch"),
            (b"NEDOS = 3000\n", "3000", "dos_nedos_mismatch"),
        ):
            with self.subTest(incar=incar, parameter=parameter):
                self.write_complete_outputs("dos")
                self.write("INCAR", incar)
                self.assert_rejected(
                    code,
                    "dos",
                    vasprun_loader=lambda _path, parameter=parameter: self.fake_vasprun(
                        parameters={"NEDOS": parameter}
                    ),
                )

        self.write_complete_outputs("dos")
        self.write("INCAR", b"NEDOS = 4000\n")
        report = self.accept(
            "dos",
            vasprun_loader=lambda _path: self.fake_vasprun(parameters={"NEDOS": 4000}),
        )
        self.assertTrue(report.accepted, report.as_dict())
        self.assertEqual(4000, report.measurements["nedos"])

    def test_dos_nedos_rejects_a_valid_line_plus_malformed_candidate(self):
        self.write_complete_outputs("dos")
        self.write("INCAR", b"NEDOS = 3000\nNEDOS malformed duplicate\n")
        self.assert_rejected("dos_nedos_invalid", "dos")

    def test_relax_contcar_must_be_pymatgen_parseable(self):
        self.write_complete_outputs("relax")
        def reject_structure(_path):
            raise ValueError("synthetic structure detail")
        report = self.assert_rejected(
            "contcar_unparseable", "relax", structure_loader=reject_structure
        )
        self.assertNotIn("synthetic", json.dumps(report.as_dict()))

    def test_vaspkit_banner_is_exact_unique_and_recorded(self):
        for content, code in (
            (b"VASPKIT Standard Edition 1.5.0\n", "vaspkit_version_invalid"),
            (
                b"VASPKIT Standard Edition 1.5.1\nVASPKIT Standard Edition 1.5.1\n",
                "vaspkit_version_invalid",
            ),
            (b"VASPKIT Standard Edition 1.5.1 extra\n", "vaspkit_version_invalid"),
            (
                b"VASPKIT Standard Edition 1.5.1\n" + b"x" * 8192,
                "evidence_too_large",
            ),
        ):
            with self.subTest(content=content):
                self.write_complete_outputs("scf")
                self.write("vaspkit-version.txt", content)
                self.assert_rejected(code)

    def test_outcar_vasp_version_is_unique_and_well_formed(self):
        marker = b" General timing and accounting informations for this job:\n"
        for content in (
            b"VASP version 6.4.3\n" + marker,
            b"vasp.6.4\n" + marker,
            b"vasp.6.4.3\nvasp.6.4.3\n" + marker,
            b"vasp.6.4.3\nvasp.6.4.2\n" + marker,
        ):
            with self.subTest(content=content):
                self.write_complete_outputs("scf")
                self.write("OUTCAR", content)
                self.assert_rejected("outcar_version_invalid")

        self.write_complete_outputs("scf")
        self.write(
            "OUTCAR",
            b"vasp.6.4.3 27Mar24\nvasp.malformed duplicate\n" + marker,
        )
        self.assert_rejected("outcar_version_invalid")

    def test_runtime_evidence_requires_one_valid_elapsed_and_peak_rss(self):
        valid_elapsed = b"Elapsed (wall clock) time (h:mm:ss or m:ss): 0:01.25\n"
        valid_rss = b"Maximum resident set size (kbytes): 123456\n"
        for content in (
            valid_rss,
            valid_elapsed,
            valid_elapsed + valid_elapsed + valid_rss,
            valid_elapsed + valid_rss + valid_rss,
            b"Elapsed (wall clock) time (h:mm:ss or m:ss): 0:61.0\n" + valid_rss,
            valid_elapsed + b"Maximum resident set size (kbytes): -1\n",
        ):
            with self.subTest(content=content):
                self.write_complete_outputs("scf")
                self.write("runtime-time.txt", content)
                self.assert_rejected("runtime_evidence_invalid")

        self.write_complete_outputs("scf")
        self.write(
            "runtime-time.txt",
            valid_elapsed
            + b"Elapsed (wall clock) time malformed duplicate\n"
            + valid_rss,
        )
        self.assert_rejected("runtime_evidence_invalid")

    def test_very_long_numeric_metadata_fails_closed_with_stable_codes(self):
        long_integer = b"9" * 5000
        self.write_complete_outputs("scf")
        self.write("vasp-exit-code.txt", long_integer + b"\n")
        self.assert_rejected("vasp_exit_invalid")

        self.write_complete_outputs("scf")
        self.write(
            "runtime-time.txt",
            b"Elapsed (wall clock) time (h:mm:ss or m:ss): 0:01.25\n"
            b"Maximum resident set size (kbytes): " + long_integer + b"\n",
        )
        self.assert_rejected("runtime_evidence_invalid")

        self.write_complete_outputs("dos")
        self.write("INCAR", b"NEDOS = " + long_integer + b"\n")
        self.assert_rejected("dos_nedos_invalid", "dos")

    def test_output_changed_during_validation_or_hash_is_rejected(self):
        self.write_complete_outputs("scf")
        original = competition_vasp._hash_opened_evidence
        changed = False

        def mutate_after_hash(opened):
            nonlocal changed
            result = original(opened)
            if opened.name == "CHGCAR" and not changed:
                changed = True
                with (self.root / "CHGCAR").open("ab") as handle:
                    handle.write(b"changed")
            return result

        with mock.patch(
            "services.competition_vasp._hash_opened_evidence", side_effect=mutate_after_hash
        ):
            self.assert_rejected("evidence_changed")

    @unittest.skipIf(os.name == "nt", "Windows cannot replace a path with an open descriptor")
    def test_output_path_replaced_after_hash_is_rejected_by_inode(self):
        self.write_complete_outputs("scf")
        original = competition_vasp._hash_opened_evidence
        swapped = False
        opened_inode = None

        def replace_after_hash(opened):
            nonlocal swapped, opened_inode
            result = original(opened)
            if opened.name == "CHGCAR" and not swapped:
                replacement = self.write("CHGCAR.replacement", b"different private evidence\n")
                opened_inode = opened.identity.st_ino
                os.replace(replacement, self.root / "CHGCAR")
                swapped = True
            return result

        with mock.patch(
            "services.competition_vasp._hash_opened_evidence", side_effect=replace_after_hash
        ):
            self.assert_rejected("evidence_changed")

        self.assertTrue(swapped)
        self.assertNotEqual(opened_inode, (self.root / "CHGCAR").stat().st_ino)
        self.assertFalse((self.root / "CHGCAR.replacement").exists())

    def test_stable_file_does_not_require_lstat_and_fstat_ctime_to_match(self):
        path = self.write("single-evidence", b"stable evidence\n")
        original_lstat = Path.lstat

        def lstat_with_cross_api_rounding(target):
            identity = original_lstat(target)
            if target != path:
                return identity
            return SimpleNamespace(
                st_dev=identity.st_dev,
                st_ino=identity.st_ino,
                st_mode=identity.st_mode,
                st_size=identity.st_size,
                st_mtime_ns=identity.st_mtime_ns,
                st_ctime_ns=identity.st_ctime_ns - 100,
            )

        with (
            mock.patch.object(Path, "lstat", autospec=True, side_effect=lstat_with_cross_api_rounding),
            competition_vasp.ExitStack() as resources,
        ):
            opened = competition_vasp._open_acceptance_evidence(
                self.root, "single-evidence", None, resources
            )
            artifact = competition_vasp._hash_opened_evidence(opened)
            competition_vasp._verify_evidence_unchanged(opened)

        self.assertEqual(hashlib.sha256(b"stable evidence\n").hexdigest(), artifact["sha256"])

    def test_invalid_stage_fails_without_reading_attempt_directory(self):
        report = self.assert_rejected("stage_invalid", "legacy")
        self.assertFalse(self.root.joinpath("OUTCAR").exists())

    def test_default_loaders_are_lazy_and_use_bounded_pymatgen_parsing_options(self):
        source = Path("services/competition_vasp.py").read_text(encoding="utf-8")
        self.assertIn("from pymatgen.io.vasp.outputs import Vasprun", source)
        self.assertIn("parse_dos=False", source)
        self.assertIn("parse_eigen=False", source)
        self.assertIn("parse_projected_eigen=False", source)
        self.assertIn("from pymatgen.core import Structure", source)
        self.assertIn("Structure.from_file(path)", source)

        from pymatgen.core import Structure
        from pymatgen.io.vasp import outputs

        vasprun_path = self.root / "vasprun.xml"
        contcar_path = self.root / "CONTCAR"
        with mock.patch.object(outputs, "Vasprun", return_value=mock.sentinel.vasprun) as loader:
            self.assertIs(
                mock.sentinel.vasprun,
                competition_vasp._default_vasprun_loader(vasprun_path),
            )
        loader.assert_called_once_with(
            vasprun_path,
            parse_dos=False,
            parse_eigen=False,
            parse_projected_eigen=False,
        )
        with mock.patch.object(
            Structure, "from_file", return_value=mock.sentinel.structure
        ) as loader:
            self.assertIs(
                mock.sentinel.structure,
                competition_vasp._default_structure_loader(contcar_path),
            )
        loader.assert_called_once_with(contcar_path)

    def test_source_does_not_reuse_legacy_vasp_authority_or_routes(self):
        source = Path("services/competition_vasp.py").read_text(encoding="utf-8")
        self.assertNotIn("spin-ase-data", source)
        self.assertNotIn("_outcar_laststep_convergence", source)
        self.assertNotIn("routers.vasp", source)


if __name__ == "__main__":
    unittest.main()
