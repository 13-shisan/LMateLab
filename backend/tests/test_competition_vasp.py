from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

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
        self.assertEqual("1.5.1", DEFAULT_POTCAR_CONTRACT.vaspkit_version)

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
