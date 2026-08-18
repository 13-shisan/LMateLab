from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import traceback
import unittest
from pathlib import Path
from unittest import mock

from services import competition_vasp
from services.competition_vasp import (
    DEFAULT_POTCAR_CONTRACT,
    FIXED_STAGE_ORDER,
    STAGE_REQUIRED_OUTPUTS,
    PotcarContract,
    VaspPolicyError,
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


if __name__ == "__main__":
    unittest.main()
