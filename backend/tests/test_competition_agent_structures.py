import io
import unittest
import zipfile

from services.competition_agent.structures import (
    StructureBuildError,
    build_structure,
    build_structure_bundle,
    list_structure_catalog,
)


class CompetitionAgentStructureTests(unittest.TestCase):
    def test_catalog_is_small_offline_and_only_mos2_is_workflow_compatible(self):
        catalog = list_structure_catalog()

        self.assertEqual(6, len(catalog))
        self.assertEqual(
            {"MoS2_monolayer", "WS2_monolayer", "MoSe2_monolayer", "WSe2_monolayer", "graphene", "hBN"},
            {item["id"] for item in catalog},
        )
        self.assertEqual(
            ["MoS2_monolayer"],
            [item["id"] for item in catalog if item["workflow_compatible"]],
        )
        for item in catalog:
            self.assertEqual("curated_sample_builder", item["source_kind"])
            self.assertNotIn("path", item)
            self.assertNotIn("api_key", item)

    def test_builder_scales_cell_layers_and_vacuum_with_bounded_vasp_files(self):
        result = build_structure(
            material_id="MoS2_monolayer",
            repeat_a=2,
            repeat_b=3,
            layers=2,
            vacuum_angstrom=18.0,
            interlayer_spacing_angstrom=6.2,
            strain_percent=1.0,
        )

        self.assertEqual("MoS2_monolayer", result["material_id"])
        self.assertEqual(36, result["summary"]["atom_count"])
        self.assertEqual(2, result["summary"]["layers"])
        self.assertEqual([2, 3], result["summary"]["in_plane_repeat"])
        self.assertGreater(result["summary"]["cell_lengths_angstrom"][2], 36.0)
        self.assertEqual(
            {"POSCAR", "INCAR", "KPOINTS", "POTCAR.spec", "manifest.json", "README.txt"},
            set(result["files"]),
        )
        self.assertNotIn("POTCAR", result["files"])
        self.assertIn("Mo S", result["files"]["POSCAR"])
        self.assertIn("ISIF   = 2", result["files"]["INCAR"])
        self.assertIn("POTCAR is not included", result["files"]["README.txt"])
        self.assertEqual(36, len(result["structure"]["symbols"]))

    def test_builder_supports_manual_and_mock_qoder_kpoint_sources(self):
        manual = build_structure(
            material_id="MoS2_monolayer",
            kpoints_source="manual",
            kpoints_mesh=[9, 11, 3],
        )
        advised = build_structure(
            material_id="MoS2_monolayer",
            repeat_a=3,
            repeat_b=2,
            kpoints_source="mock_qoder",
        )

        self.assertEqual([9, 11, 3], manual["kpoints"]["mesh"])
        self.assertEqual("manual", manual["kpoints"]["source"])
        self.assertIn("9 11 3", manual["files"]["KPOINTS"])
        self.assertEqual([5, 8, 1], advised["kpoints"]["mesh"])
        self.assertEqual("mock_qoder", advised["kpoints"]["source"])
        self.assertTrue(advised["kpoints"]["advisory"])

    def test_builder_rejects_unsafe_kpoint_meshes(self):
        for mesh in ([0, 12, 1], [61, 12, 1], [12, 12, 0], [12, 12, 61], [12, 12], [True, 12, 1]):
            with self.subTest(mesh=mesh):
                with self.assertRaises(StructureBuildError):
                    build_structure(
                        material_id="MoS2_monolayer",
                        kpoints_source="manual",
                        kpoints_mesh=mesh,
                    )

    def test_every_catalog_entry_builds_a_finite_default_structure(self):
        for item in list_structure_catalog():
            with self.subTest(material_id=item["id"]):
                result = build_structure(material_id=item["id"])
                self.assertGreater(result["summary"]["atom_count"], 0)
                self.assertTrue(all(value > 0 for value in result["summary"]["cell_lengths_angstrom"]))
                self.assertEqual(result["summary"]["atom_count"], len(result["structure"]["positions"]))
                self.assertEqual(item["workflow_compatible"], result["workflow_compatible"])

    def test_builder_rejects_unknown_material_and_unsafe_size_controls(self):
        invalid = [
            {"material_id": "../MoS2"},
            {"material_id": "MoS2_monolayer", "repeat_a": 0},
            {"material_id": "MoS2_monolayer", "repeat_b": 7},
            {"material_id": "MoS2_monolayer", "layers": 9},
            {"material_id": "MoS2_monolayer", "vacuum_angstrom": 50.0},
            {"material_id": "MoS2_monolayer", "strain_percent": float("nan")},
            {
                "material_id": "WSe2_monolayer",
                "repeat_a": 6,
                "repeat_b": 6,
                "layers": 8,
            },
        ]
        for parameters in invalid:
            with self.subTest(parameters=parameters):
                with self.assertRaises(StructureBuildError):
                    build_structure(**parameters)

    def test_bundle_contains_only_fixed_flat_file_names(self):
        content = build_structure_bundle(material_id="graphene", vacuum_angstrom=20.0)

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(
                ["INCAR", "KPOINTS", "POSCAR", "POTCAR.spec", "README.txt", "manifest.json"],
                sorted(archive.namelist()),
            )
            self.assertTrue(all("/" not in name and "\\" not in name for name in archive.namelist()))
            self.assertNotIn("POTCAR", archive.namelist())


if __name__ == "__main__":
    unittest.main()
