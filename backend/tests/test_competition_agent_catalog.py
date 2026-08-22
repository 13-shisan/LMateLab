import unittest

from services.competition_agent.catalog import (
    APPLICABLE_TEMPLATE_IDS,
    get_template,
    list_templates,
)


class CompetitionAgentCatalogTests(unittest.TestCase):
    def test_only_fixed_mos2_templates_are_applicable(self):
        self.assertEqual(
            {
                "2d_relax",
                "band_scf",
                "band_nscf",
                "dos",
            },
            APPLICABLE_TEMPLATE_IDS,
        )
        applicable = [item for item in list_templates() if item["applicable"]]
        self.assertEqual(
            APPLICABLE_TEMPLATE_IDS,
            {item["id"] for item in applicable},
        )
        self.assertTrue(all(item["material_id"] == "MoS2_monolayer" for item in applicable))

    def test_unknown_template_fails_closed(self):
        with self.assertRaisesRegex(KeyError, "template is unavailable"):
            get_template("../../POTCAR")

    def test_catalog_never_exposes_paths_commands_or_potcar(self):
        rendered = repr(list_templates()).lower()
        for forbidden in ["potcar", "sbatch", "scancel", "/home/", "../"]:
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
