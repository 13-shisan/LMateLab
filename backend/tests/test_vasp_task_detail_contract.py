import json
import unittest
from types import SimpleNamespace

from services.vasp_task_detail import build_public_task_detail, get_optional_ase_row


class VaspTaskDetailContractTests(unittest.TestCase):
    def _row(self):
        return SimpleNamespace(
            id=237943,
            formula="Cu4In4P8S24",
            energy=-192.67317127,
            fmax=0.00891234,
            natoms=40,
            pbc=[True, True, True],
            calculator="vasp",
            calculator_parameters={"encut": 520},
            key_value_pairs={"phys_spacegroup_international": "P1"},
            data={
                "source_dir": "/storage/private/calculation",
                "calculator_parameters": {"encut": 520},
                "phys_bandgap_eV": 1.5708,
                "phys_vbm_eV": 4.3278,
                "phys_cbm_eV": 5.8986,
            },
        )

    def test_public_payload_uses_allowlisted_row_and_property_fields(self):
        payload = build_public_task_detail(
            row=self._row(),
            db={"key": "personal:jbwu:Pwjb.db", "dbname": "Pwjb.db"},
            structure={"symbols": ["Cu", "In", "P", "S"]},
            crystal={"dimensionality": 3},
            has_vasprun=False,
            has_outcar=False,
        )

        self.assertEqual(
            {"id", "formula", "energy", "fmax", "natoms", "pbc"},
            set(payload["row"]),
        )
        self.assertEqual("P1", payload["properties"]["spacegroup"])
        self.assertEqual(1.5708, payload["properties"]["bandgap_eV"])
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("source_dir", serialized)
        self.assertNotIn("/storage/private", serialized)
        self.assertNotIn("calculator_parameters", serialized)

    def test_missing_source_files_disable_electronic_capabilities(self):
        payload = build_public_task_detail(
            row=self._row(),
            db={"key": "personal:jbwu:Pwjb.db", "dbname": "Pwjb.db"},
            structure={},
            crystal={},
            has_vasprun=False,
            has_outcar=False,
        )

        self.assertEqual(
            {
                "structure_export": True,
                "band_plot": False,
                "band_data": False,
                "dos_plot": False,
                "dos_data": False,
            },
            payload["capabilities"],
        )

    def test_vasprun_or_outcar_enables_electronic_capabilities(self):
        for has_vasprun, has_outcar in ((True, False), (False, True)):
            with self.subTest(vasprun=has_vasprun, outcar=has_outcar):
                payload = build_public_task_detail(
                    row=self._row(),
                    db={"key": "personal:jbwu:Pwjb.db", "dbname": "Pwjb.db"},
                    structure={},
                    crystal={},
                    has_vasprun=has_vasprun,
                    has_outcar=has_outcar,
                )
                self.assertTrue(payload["capabilities"]["band_plot"])
                self.assertTrue(payload["capabilities"]["dos_data"])

    def test_missing_ase_row_returns_none_without_masking_valid_rows(self):
        valid_row = self._row()

        class MissingConnection:
            def get(self, **_kwargs):
                raise KeyError("no match")

        class ValidConnection:
            def get(self, **_kwargs):
                return valid_row

        self.assertIsNone(get_optional_ase_row(MissingConnection(), 999999999))
        self.assertIs(valid_row, get_optional_ase_row(ValidConnection(), 237943))


if __name__ == "__main__":
    unittest.main()
