import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SLURM = ROOT / "deploy" / "107cup" / "slurm" / "stage10-acceptance.slurm"
HARNESS = ROOT / "deploy" / "107cup" / "slurm" / "stage10-acceptance.py"
SUBMIT = ROOT / "deploy" / "107cup" / "submit-stage10-acceptance.sh"
GENERATOR = ROOT / "deploy" / "107cup" / "generate-stage10-manifest.py"
DELIVERY_DOCS = (
    ROOT / "docs" / "107cup" / "deployment.md",
    ROOT / "docs" / "107cup" / "data-and-provenance.md",
    ROOT / "docs" / "107cup" / "demo-script.md",
    ROOT / "docs" / "107cup" / "final-acceptance.md",
)
MANIFEST = ROOT / "docs" / "107cup" / "artifacts" / "manifest.sha256"


class Stage10DeliveryContractTests(unittest.TestCase):
    def test_acceptance_runs_on_slurm_and_reuses_read_only_stage8_gate(self):
        slurm = SLURM.read_text(encoding="utf-8")
        harness = HARNESS.read_text(encoding="utf-8")

        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-A100",
            "#SBATCH --time=00:20:00",
            "SLURM_JOB_ID",
            "LMATELAB_COORDINATOR_ENABLED=0",
            "stage10-acceptance.py",
        ):
            self.assertIn(required, slurm)
        for forbidden in ("vasp_std", "vasp_gam", "vasp_ncl", "vaspkit", "\nsbatch "):
            self.assertNotIn(forbidden, slurm.lower())

        for required in (
            "4b566547-961b-4e10-a8d0-99431f2e2229",
            "db9c793d-cf8f-4207-823b-5943d825f21d",
            "a99e338c6a00fa2d1129bf9fbbe910a959f3c419955370f995da8242850ba8b4",
            "7addf0ede65844a211e1460d0e53fc4f88792e7928c0af2541bc791e7595ae0e",
            "PRAGMA query_only=ON",
            "run_acceptance",
            "STAGE10_ACCEPTANCE_OK",
        ):
            self.assertIn(required, harness)
        for forbidden in ("session.commit", "subprocess", "sbatch", "scancel"):
            self.assertNotIn(forbidden, harness)

    def test_submit_helper_pins_clean_merged_main_and_only_submits_acceptance(self):
        source = SUBMIT.read_text(encoding="utf-8")
        for required in (
            'git -C "$project" status --porcelain',
            'git -C "$project" rev-parse origin/main',
            'git -C "$project" rev-parse HEAD',
            "commit.txt",
            "stage10-acceptance.slurm",
            "sbatch --parsable",
            "stage10-acceptance-job-id",
        ):
            self.assertIn(required, source)
        self.assertNotIn("submit-build.sh", source)
        self.assertNotIn("submit-service.sh", source)

    def test_delivery_documents_exist_and_keep_external_review_open(self):
        for path in DELIVERY_DOCS:
            self.assertTrue(path.is_file(), path)
            self.assertGreater(len(path.read_text(encoding="utf-8")), 500, path)

        acceptance = DELIVERY_DOCS[-1].read_text(encoding="utf-8")
        self.assertIn("PARTIAL", acceptance)
        self.assertIn("三名成员", acceptance)
        self.assertIn("不得提交新的 VASP", acceptance)

    def test_manifest_is_canonical_complete_and_matches_files(self):
        source = GENERATOR.read_text(encoding="utf-8")
        self.assertIn("STAGE10_MANIFEST_PATHS", source)
        self.assertIn("os.open", source)
        self.assertNotIn("glob(", source)

        entries = MANIFEST.read_text(encoding="ascii").splitlines()
        self.assertGreaterEqual(len(entries), 10)
        self.assertEqual(entries, sorted(entries, key=lambda line: line.split("  ", 1)[1]))
        self.assertEqual(len(entries), len(set(entries)))
        for line in entries:
            match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_./-]+)", line)
            self.assertIsNotNone(match, line)
            digest, relative = match.groups()
            self.assertNotEqual(relative, "docs/107cup/artifacts/manifest.sha256")
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest(), relative)


if __name__ == "__main__":
    unittest.main()
