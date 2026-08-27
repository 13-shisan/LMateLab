import hashlib
import json
import math
import os
import stat
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from services.competition_inputs import (
    InputValidationError,
    load_template,
    materialize_inputs,
    parse_structure_bytes,
    validate_draft_payload,
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

VALID_CIF = b"""data_MoS2
_cell_length_a 3.180000
_cell_length_b 3.180000
_cell_length_c 20.000000
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
S1 S 0.333333 0.666667 0.578000
Mo1 Mo 0.000000 0.000000 0.500000
S2 S 0.333333 0.666667 0.422000
"""

VALID_WS2_POSCAR = b"""WS2
1.0
3.153 0.0 0.0
-1.5765 2.7308 0.0
0.0 0.0 20.0
W S
1 2
Direct
0.0 0.0 0.5
0.666667 0.333333 0.579
0.333333 0.666667 0.421
"""

FIXED_STEPS = ["relax", "scf", "band", "dos"]


def valid_payload(**overrides):
    payload = {
        "template_version": "mos2_v1",
        "source_kind": "builtin",
        "steps": list(FIXED_STEPS),
        "parameters": {},
    }
    payload.update(overrides)
    return payload


def generic_upload_payload(**overrides):
    payload = {
        "template_version": "pbe_2d_v1",
        "source_kind": "upload",
        "structure_upload_id": str(uuid.uuid4()),
        "steps": list(FIXED_STEPS),
        "parameters": {},
    }
    payload.update(overrides)
    return payload


def poscar_with_symbols(symbols, counts):
    total = sum(counts)
    positions = "\n".join("0.0 0.0 0.5" for _ in range(total))
    return (
        "generated\n1.0\n3.18 0 0\n-1.59 2.753961 0\n0 0 20\n"
        f"{' '.join(symbols)}\n{' '.join(str(value) for value in counts)}\n"
        f"Direct\n{positions}\n"
    ).encode("ascii")


class StructureParsingTests(unittest.TestCase):
    def test_rejects_vasp_count_bomb_before_ase_allocates_atoms(self):
        count_bombs = (
            b"""count bomb
1.0
3.18 0 0
-1.59 2.753961 0
0 0 20
Mo S
100000000 200000000
Direct
""",
            (
                "count token bomb\n1.0\n3.18 0 0\n-1.59 2.753961 0\n0 0 20\n"
                f"Mo S\n{'9' * 10000} 2\nDirect\n"
            ).encode("ascii"),
        )
        with mock.patch("services.competition_inputs.ase_read") as read_structure:
            for count_bomb in count_bombs:
                with self.subTest(count_line=count_bomb.splitlines()[6][:40]):
                    with self.assertRaisesRegex(InputValidationError, "200 atoms"):
                        parse_structure_bytes(count_bomb, "structure.dat")

        read_structure.assert_not_called()

    def test_rejects_empty_oversize_binary_and_path_filenames(self):
        invalid_cases = (
            (b"", "POSCAR"),
            (b" \r\n\t", "POSCAR"),
            (b"x" * (1024 * 1024 + 1), "POSCAR"),
            (b"abc\x00def", "POSCAR"),
            (b"\xff\xfe\xfd", "POSCAR"),
            (VALID_POSCAR, "../POSCAR"),
            (VALID_POSCAR, "nested/POSCAR"),
            (VALID_POSCAR, "nested\\POSCAR"),
            (VALID_POSCAR, "POS..CAR"),
        )
        for content, filename in invalid_cases:
            with self.subTest(filename=filename, size=len(content)):
                with self.assertRaises(InputValidationError):
                    parse_structure_bytes(content, filename)

    def test_rejects_content_that_neither_vasp_nor_cif_can_parse(self):
        with self.assertRaises(InputValidationError) as raised:
            parse_structure_bytes(b"this is not a structure\n", "structure.dat")
        self.assertIn("vasp", str(raised.exception).lower())
        self.assertIn("cif", str(raised.exception).lower())

    def test_rejects_too_many_atoms_and_invalid_or_duplicate_element_headers(self):
        invalid_structures = (
            poscar_with_symbols(["Mo", "S"], [67, 134]),
            poscar_with_symbols(["Xx", "S"], [1, 2]),
            poscar_with_symbols(["Mo", "S", "Mo"], [1, 2, 1]),
        )
        for content in invalid_structures:
            with self.subTest(atom_line=content.splitlines()[5]):
                with self.assertRaises(InputValidationError):
                    parse_structure_bytes(content, "structure.any")

    def test_accepts_general_grouped_vasp_elements_and_preserves_order(self):
        parsed = parse_structure_bytes(VALID_WS2_POSCAR, "WS2.vasp")

        self.assertEqual("vasp", parsed.source_format)
        self.assertEqual("WS2", parsed.summary["formula"])
        self.assertEqual(["W", "S"], parsed.summary["elements"])
        self.assertEqual({"W": 1, "S": 2}, parsed.summary["counts"])
        self.assertEqual([b"W", b"S"], parsed.canonical_poscar.splitlines()[5].split())

    def test_accepts_vasp_based_on_content_not_filename(self):
        parsed = parse_structure_bytes(VALID_POSCAR, "uploaded.cif")

        self.assertEqual(parsed.source_format, "vasp")
        self.assertEqual(parsed.summary["formula"], "MoS2")
        self.assertEqual(parsed.summary["atom_count"], 3)
        self.assertEqual(parsed.summary["elements"], ["Mo", "S"])
        self.assertEqual(parsed.summary["counts"], {"Mo": 1, "S": 2})
        self.assertEqual(parsed.original_filename, "uploaded.cif")
        self.assertEqual(parsed.canonical_poscar.splitlines()[5].split(), [b"Mo", b"S"])

    def test_accepts_cif_based_on_content_and_canonicalizes_mo_before_s(self):
        parsed = parse_structure_bytes(VALID_CIF, "POSCAR")

        self.assertEqual(parsed.source_format, "cif")
        self.assertEqual(parsed.summary["formula"], "MoS2")
        self.assertEqual(parsed.summary["elements"], ["Mo", "S"])
        self.assertEqual(parsed.canonical_poscar.splitlines()[5].split(), [b"Mo", b"S"])
        reparsed = parse_structure_bytes(parsed.canonical_poscar, "canonical")
        self.assertEqual(reparsed.source_format, "vasp")
        self.assertEqual(reparsed.summary["counts"], {"Mo": 1, "S": 2})

    def test_rejects_non_finite_cells_and_direct_or_cartesian_positions(self):
        invalid_structures = (
            VALID_POSCAR.replace(b"3.180000 0.000000 0.000000", b"nan 0.000000 0.000000"),
            VALID_POSCAR.replace(b"3.180000 0.000000 0.000000", b"inf 0.000000 0.000000"),
            VALID_POSCAR.replace(b"0.333333 0.666667 0.578000", b"nan 0.666667 0.578000"),
            VALID_POSCAR.replace(b"0.333333 0.666667 0.578000", b"inf 0.666667 0.578000"),
            VALID_POSCAR.replace(
                b"Direct\n0.000000 0.000000 0.500000",
                b"Cartesian\ninf 0.000000 0.500000",
            ),
        )
        for content in invalid_structures:
            with self.subTest(line=next(line for line in content.splitlines() if b"nan" in line or b"inf" in line)):
                with self.assertRaises(InputValidationError):
                    parse_structure_bytes(content, "structure")

    def test_rejects_zero_and_singular_periodic_cells(self):
        invalid_structures = (
            VALID_POSCAR.replace(
                b"3.180000 0.000000 0.000000\n-1.590000 2.753961 0.000000\n0.000000 0.000000 20.000000",
                b"0 0 0\n0 0 0\n0 0 0",
            ),
            VALID_POSCAR.replace(
                b"-1.590000 2.753961 0.000000",
                b"6.360000 0.000000 0.000000",
            ),
        )
        for content in invalid_structures:
            with self.subTest(cell=content.splitlines()[2:5]):
                with self.assertRaises(InputValidationError):
                    parse_structure_bytes(content, "structure")

    def test_wraps_canonical_poscar_writer_failures_as_validation_errors(self):
        with mock.patch(
            "services.competition_inputs.ase_write",
            side_effect=RuntimeError("writer rejected structure"),
        ):
            with self.assertRaisesRegex(InputValidationError, "canonical POSCAR"):
                parse_structure_bytes(VALID_POSCAR, "POSCAR")


class TemplateValidationTests(unittest.TestCase):
    def test_loads_legacy_and_generic_canonical_templates_only(self):
        template = load_template("mos2_v1")

        self.assertEqual(template["template_version"], "mos2_v1")
        self.assertEqual(template["material"], "MoS2")
        self.assertEqual(
            [step["key"] for step in template["steps"]],
            FIXED_STEPS,
        )
        self.assertEqual(
            [step["depends_on"] for step in template["steps"]],
            [[], ["relax"], ["scf"], ["scf"]],
        )
        encoded = json.dumps(
            template,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        template_path = (
            Path(__file__).parents[1]
            / "competition_templates"
            / "mos2_v1"
            / "template.json"
        )
        self.assertEqual(template_path.read_text(encoding="utf-8"), encoded + "\n")

        generic = load_template("pbe_2d_v1")
        self.assertEqual("pbe_2d_v1", generic["template_version"])
        self.assertEqual("structure_elements", generic["potcar_policy"]["source"])
        band = next(step for step in generic["steps"] if step["key"] == "band")
        self.assertEqual({"mode": "vaspkit", "task": 302}, band["kpoints"])
        with self.assertRaises(InputValidationError):
            load_template("mos2_v2")

    def test_validates_builtin_and_upload_payloads(self):
        builtin = validate_draft_payload(valid_payload())
        upload_id = str(uuid.uuid4())
        upload = validate_draft_payload(
            valid_payload(source_kind="upload", structure_upload_id=upload_id)
        )

        self.assertEqual(builtin["source_kind"], "builtin")
        self.assertNotIn("structure_upload_id", builtin)
        self.assertEqual(upload["structure_upload_id"], upload_id)
        self.assertEqual(upload["steps"], FIXED_STEPS)
        self.assertEqual(json.loads(builtin["canonical_json"])["steps"], FIXED_STEPS)

        generic = validate_draft_payload(generic_upload_payload())
        self.assertEqual("pbe_2d_v1", generic["template_version"])
        with self.assertRaisesRegex(InputValidationError, "requires an uploaded structure"):
            validate_draft_payload(
                generic_upload_payload(source_kind="builtin", structure_upload_id=None)
            )

    def test_rejects_extra_fields_invalid_source_and_wrong_fixed_steps(self):
        invalid_payloads = (
            valid_payload(extra=True),
            valid_payload(template_version="mos2_v2"),
            valid_payload(source_kind="local"),
            valid_payload(structure_upload_id=str(uuid.uuid4())),
            valid_payload(source_kind="upload"),
            valid_payload(source_kind="upload", structure_upload_id="not-a-uuid"),
            valid_payload(steps=["relax", "scf", "dos", "band"]),
            valid_payload(steps=["relax", "scf", "band"]),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(InputValidationError):
                    validate_draft_payload(payload)

    def test_rejects_unknown_step_and_incar_parameter_keys(self):
        invalid_parameters = (
            {"phonon": {"ENCUT": 520}},
            {"relax": {"SYSTEM": 1}},
            {"relax": {"encut": 520}},
            {"band": {"NEDOS": 2000}},
        )
        for parameters in invalid_parameters:
            with self.subTest(parameters=parameters):
                with self.assertRaises(InputValidationError):
                    validate_draft_payload(valid_payload(parameters=parameters))

    def test_rejects_booleans_non_finite_numbers_and_out_of_range_values(self):
        invalid_values = (
            ("relax", "ENCUT", True),
            ("relax", "ENCUT", math.nan),
            ("relax", "ENCUT", math.inf),
            ("relax", "ENCUT", -math.inf),
            ("relax", "ENCUT", 399.9),
            ("relax", "ENCUT", 700.1),
            ("relax", "EDIFF", 0),
            ("relax", "EDIFFG", 0.01),
            ("relax", "NSW", 1.5),
            ("scf", "NELM", 301),
            ("dos", "NEDOS", 99),
        )
        for step, key, value in invalid_values:
            with self.subTest(step=step, key=key, value=value):
                with self.assertRaises(InputValidationError):
                    validate_draft_payload(
                        valid_payload(parameters={step: {key: value}})
                    )

    def test_rejects_string_and_command_injection_parameter_values(self):
        invalid_strings = (
            "520",
            "520; rm -rf work",
            "520\nSYSTEM = injected",
            "`touch owned`",
            "$(touch owned)",
        )
        for value in invalid_strings:
            with self.subTest(value=value):
                with self.assertRaises(InputValidationError):
                    validate_draft_payload(
                        valid_payload(parameters={"relax": {"ENCUT": value}})
                    )

    def test_accepts_finite_in_range_numeric_overrides_and_canonicalizes_json(self):
        validated = validate_draft_payload(
            valid_payload(
                parameters={
                    "relax": {"SIGMA": 0.1, "ENCUT": 600, "NSW": 120},
                    "dos": {"NEDOS": 4000},
                }
            )
        )

        self.assertEqual(
            validated["parameters"],
            {
                "dos": {"NEDOS": 4000},
                "relax": {"ENCUT": 600, "NSW": 120, "SIGMA": 0.1},
            },
        )
        self.assertEqual(
            validated["canonical_json"],
            '{"parameters":{"dos":{"NEDOS":4000},"relax":{"ENCUT":600,'
            '"NSW":120,"SIGMA":0.1}},"source_kind":"builtin","steps":['
            '"relax","scf","band","dos"],"template_version":"mos2_v1"}',
        )

    def test_accepts_controlled_kpoint_meshes_and_rejects_band_override(self):
        kpoints = {
            "source": "mock_qoder",
            "meshes": {"relax": [10, 10, 2], "scf": [16, 16, 3], "dos": [22, 22, 4]},
        }
        validated = validate_draft_payload(valid_payload(kpoints=kpoints))

        self.assertEqual(kpoints, validated["kpoints"])
        self.assertEqual(kpoints, json.loads(validated["canonical_json"])["kpoints"])
        for invalid in (
            {"source": "qoder", "meshes": kpoints["meshes"]},
            {"source": "manual", "meshes": {**kpoints["meshes"], "band": [8, 8, 1]}},
            {"source": "manual", "meshes": {"relax": [0, 8, 1]}},
            {"source": "manual", "meshes": {"relax": [8, 8, 0]}},
        ):
            with self.subTest(kpoints=invalid):
                with self.assertRaises(InputValidationError):
                    validate_draft_payload(valid_payload(kpoints=invalid))


class MaterializationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.workflow_root = Path(self.temp_dir.name) / "workflows"
        self.structure = parse_structure_bytes(VALID_POSCAR, "POSCAR")
        self.payload = validate_draft_payload(valid_payload())

    def test_materializes_fixed_inputs_kpoints_potcar_identity_and_hashes(self):
        upload_payload = validate_draft_payload(
            valid_payload(
                source_kind="upload",
                structure_upload_id=str(uuid.uuid4()),
            )
        )
        result = materialize_inputs(self.workflow_root, self.structure, upload_payload)

        self.assertEqual(str(uuid.UUID(result["directory_id"])), result["directory_id"])
        directory = self.workflow_root / result["directory_id"]
        self.assertEqual(Path(result["directory"]).resolve(), directory.resolve())
        self.assertEqual(
            sorted(path.name for path in directory.iterdir()),
            sorted(FIXED_STEPS),
        )
        self.assertFalse(any(path.name == "POTCAR" for path in directory.rglob("*")))
        expected_relative_paths = {
            f"{result['directory_id']}/{step}/{name}"
            for step in FIXED_STEPS
            for name in ("INCAR", "KPOINTS", "POSCAR", "POTCAR.spec")
        }
        self.assertEqual(
            {record["relative_path"] for record in result["files"]},
            expected_relative_paths,
        )

        for record in result["files"]:
            path = self.workflow_root / record["relative_path"]
            content = path.read_bytes()
            self.assertEqual(record["size_bytes"], len(content))
            self.assertEqual(record["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(record["step_key"], path.parent.name)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            for child in directory.iterdir():
                self.assertEqual(stat.S_IMODE(child.stat().st_mode), 0o700)

        self.assertEqual((directory / "relax" / "POTCAR.spec").read_text(), "Mo_sv\nS\n")
        self.assertIn("12 12 1", (directory / "relax" / "KPOINTS").read_text())
        self.assertIn("18 18 1", (directory / "scf" / "KPOINTS").read_text())
        self.assertIn("Line-mode", (directory / "band" / "KPOINTS").read_text())
        self.assertIn("24 24 1", (directory / "dos" / "KPOINTS").read_text())
        self.assertNotIn("potcar_sha256", result)

    def test_materializes_builtin_structure_and_applies_validated_overrides(self):
        payload = validate_draft_payload(
            valid_payload(parameters={"relax": {"ENCUT": 600}, "dos": {"NEDOS": 4000}})
        )
        result = materialize_inputs(self.workflow_root, None, payload)
        directory = Path(result["directory"])

        self.assertIn("ENCUT = 600", (directory / "relax" / "INCAR").read_text())
        self.assertIn("NEDOS = 4000", (directory / "dos" / "INCAR").read_text())
        parsed = parse_structure_bytes((directory / "scf" / "POSCAR").read_bytes(), "POSCAR")
        self.assertEqual(parsed.summary["formula"], "MoS2")

    def test_materializes_ws2_with_structure_potcars_and_vaspkit_302_policy(self):
        structure = parse_structure_bytes(VALID_WS2_POSCAR, "WS2.vasp")
        payload = validate_draft_payload(generic_upload_payload())

        result = materialize_inputs(self.workflow_root, structure, payload)
        directory = Path(result["directory"])

        self.assertEqual("pbe_2d_v1", result["template_version"])
        self.assertEqual("WS2", result["structure_summary"]["formula"])
        for step in FIXED_STEPS:
            self.assertEqual("W\nS\n", (directory / step / "POTCAR.spec").read_text())
        self.assertFalse((directory / "band" / "KPOINTS").exists())
        self.assertEqual(
            '{"generator":"vaspkit","task":302,"version":1}\n',
            (directory / "band" / "BAND_PATH.policy").read_text(),
        )
        self.assertIn("LMateLab PBE", (directory / "relax" / "INCAR").read_text())

    def test_materializes_reviewed_kpoints_but_keeps_band_path_fixed(self):
        payload = validate_draft_payload(valid_payload(kpoints={
            "source": "manual",
            "meshes": {"relax": [9, 9, 2], "scf": [15, 15, 3], "dos": [21, 21, 4]},
        }))
        result = materialize_inputs(self.workflow_root, None, payload)
        directory = Path(result["directory"])

        self.assertIn("9 9 2", (directory / "relax" / "KPOINTS").read_text())
        self.assertIn("15 15 3", (directory / "scf" / "KPOINTS").read_text())
        self.assertIn("21 21 4", (directory / "dos" / "KPOINTS").read_text())
        band = (directory / "band" / "KPOINTS").read_text()
        self.assertIn("Line-mode", band)
        self.assertIn("! G", band)

    def test_rejects_structure_source_mismatch_and_root_that_is_a_file(self):
        upload_payload = validate_draft_payload(
            valid_payload(
                source_kind="upload",
                structure_upload_id=str(uuid.uuid4()),
            )
        )
        with self.assertRaises(InputValidationError):
            materialize_inputs(self.workflow_root, None, upload_payload)
        with self.assertRaises(InputValidationError):
            materialize_inputs(self.workflow_root, self.structure, self.payload)

        root_file = Path(self.temp_dir.name) / "not-a-directory"
        root_file.write_text("occupied")
        with self.assertRaises(InputValidationError):
            materialize_inputs(root_file, None, self.payload)

    def test_failed_write_does_not_leave_completed_uuid_directory(self):
        original_write_bytes = Path.write_bytes
        writes = 0

        def fail_during_write(path, content):
            nonlocal writes
            writes += 1
            if writes == 3:
                raise OSError("simulated disk failure")
            return original_write_bytes(path, content)

        with mock.patch("pathlib.Path.write_bytes", new=fail_during_write):
            with self.assertRaises(OSError):
                materialize_inputs(self.workflow_root, None, self.payload)

        self.assertTrue(self.workflow_root.is_dir())
        self.assertEqual(list(self.workflow_root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
