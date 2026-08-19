import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SLURM = ROOT / "deploy" / "107cup" / "slurm" / "stage8-acceptance.slurm"
HARNESS = ROOT / "deploy" / "107cup" / "slurm" / "stage8-acceptance.py"


class Stage8AcceptanceContractTests(unittest.TestCase):
    def test_slurm_job_is_compute_only_read_only_acceptance(self):
        source = SLURM.read_text(encoding="utf-8")
        self.assertIn("#SBATCH --partition=P107-A100", source)
        self.assertIn("#SBATCH --time=00:20:00", source)
        self.assertIn("LMATELAB_COORDINATOR_ENABLED=0", source)
        self.assertIn("stage8-acceptance.py", source)
        self.assertNotIn("vasp-stage.slurm", source)
        self.assertNotIn("sbatch ", source)
        self.assertNotIn("vasp_std", source)

    def test_harness_uses_fixed_stage7_workflows_and_never_mutates_them(self):
        source = HARNESS.read_text(encoding="utf-8")
        self.assertIn("4b566547-961b-4e10-a8d0-99431f2e2229", source)
        self.assertIn("db9c793d-cf8f-4207-823b-5943d825f21d", source)
        self.assertLess(source.index("import models"), source.index("from models_workflow import"))
        self.assertIn("PRAGMA query_only=ON", source)
        self.assertIn("STAGE8_ACCEPTANCE_OK", source)
        self.assertNotIn("session.commit", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("sbatch", source)


if __name__ == "__main__":
    unittest.main()
