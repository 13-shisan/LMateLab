import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class CompetitionAgentSecurityTests(unittest.TestCase):
    def test_agent_runtime_has_no_scheduler_filesystem_or_process_adapter(self):
        source_root = BACKEND_ROOT / "services" / "competition_agent"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(source_root.glob("*.py"))
        ).lower()
        for forbidden in [
            "competition_slurm",
            "subprocess",
            "os.system",
            "shell=true",
            "sbatch",
            "scancel",
        ]:
            self.assertNotIn(forbidden, source)

    def test_worker_slurm_only_processes_agent_queue(self):
        source = (BACKEND_ROOT.parent / "deploy" / "107cup" / "agent-worker.slurm").read_text(encoding="utf-8")
        self.assertIn("services.competition_agent.worker", source)
        self.assertIn("--poll-seconds 1 --max-idle-cycles 0", source)
        self.assertIn('source "$runtime_env"', source)
        self.assertNotIn("QODERCN_PERSONAL_ACCESS_TOKEN", source)
        for forbidden in ["sbatch ", "scancel ", "vasp_std", "POTCAR"]:
            self.assertNotIn(forbidden, source)

    def test_qoder_management_uses_only_fixed_subprocess_calls(self):
        source = (BACKEND_ROOT / "services" / "qoder_management.py").read_text(encoding="utf-8").lower()
        self.assertIn('qodercn_sdk_version = "1.0.14"', source)
        self.assertIn('"qoderclicn"', source)
        self.assertIn('"remote-control"', source)
        self.assertIn('"--capacity", "1"', source)
        for forbidden in ["shell=true", "os.system", "sbatch", "scancel", '"pip", "install"']:
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
