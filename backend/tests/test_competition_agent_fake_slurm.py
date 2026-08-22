import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import services.competition_slurm as competition_slurm
from services.competition_agent.qoder_runtime import MockQoderRuntime
from services.competition_slurm import SlurmBinaries, SlurmClient, SlurmSubmission


class RecordingFakeSlurm:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        return subprocess.CompletedProcess(argv, 0, b"73001\n", b"")


class CompetitionAgentFakeSlurmTests(unittest.TestCase):
    def test_agent_advises_then_application_owned_adapter_submits_fixed_fake_job(self):
        recommendation = MockQoderRuntime().run(
            request_kind="template_recommendation",
            prompt="Recommend the relax template",
            tool_payload={"templates": [{"id": "2d_relax"}]},
        )
        self.assertEqual("2d_relax", recommendation["citations"][0]["id"])
        self.assertNotIn("submit", repr(recommendation).lower())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow_id = str(uuid.uuid4())
            attempt_id = str(uuid.uuid4())
            attempt_dir = root / workflow_id / "attempts" / attempt_id
            attempt_dir.mkdir(parents=True)
            script = root / "probe.slurm"
            script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            executor = RecordingFakeSlurm()
            client = SlurmClient(
                binaries=SlurmBinaries(
                    sbatch="/usr/bin/sbatch",
                    squeue="/usr/bin/squeue",
                    scontrol="/usr/bin/scontrol",
                    sacct="/usr/bin/sacct",
                    scancel="/usr/bin/scancel",
                ),
                executor=executor,
                allowed_scripts=(script,),
                workflow_root=root,
            )
            submission = SlurmSubmission(
                workflow_id=workflow_id,
                attempt_id=attempt_id,
                step_key="relax",
                attempt_number=1,
                attempt_directory=attempt_dir,
                script_path=script,
                runner_kind="probe",
                runner_mode="success",
            )

            def test_snapshot_descriptor():
                with tempfile.TemporaryFile(mode="w+b") as handle:
                    return os.dup(handle.fileno())

            with mock.patch.object(
                competition_slurm,
                "_create_private_snapshot_descriptor",
                side_effect=test_snapshot_descriptor,
            ):
                job_id = client.submit(submission)

        self.assertEqual("73001", job_id)
        argv, kwargs = executor.calls[0]
        self.assertEqual("/usr/bin/sbatch", argv[0])
        self.assertIn("--job-name=lmatelab-", " ".join(argv))
        self.assertEqual(["success", workflow_id, attempt_id], argv[-3:])
        self.assertIs(False, kwargs["shell"])


if __name__ == "__main__":
    unittest.main()
