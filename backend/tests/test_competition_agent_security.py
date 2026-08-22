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
        self.assertIn("--poll-seconds 1 --max-idle-cycles 240", source)
        self.assertNotIn("QODER_PERSONAL_ACCESS_TOKEN", source)
        for forbidden in ["sbatch ", "scancel ", "vasp_std", "POTCAR"]:
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
