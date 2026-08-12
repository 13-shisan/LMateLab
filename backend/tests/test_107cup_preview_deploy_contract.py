import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_ROOT = REPO_ROOT / "deploy" / "107cup"


class CompetitionPreviewDeployContractTests(unittest.TestCase):
    def read_required(self, name: str) -> str:
        path = DEPLOY_ROOT / name
        self.assertTrue(path.is_file(), str(path))
        return path.read_text(encoding="utf-8")

    def test_preview_build_never_promotes_current(self):
        source = self.read_required("preview-build.slurm")
        for required in (
            "SLURM_JOB_ID",
            "LMATELAB_PREVIEW_COMMIT",
            "origin/main",
            "previews",
            "VITE_COMPETITION_DATA_MODE=demo",
            "manifest.sha256",
            "npm ci",
            "npm test",
            "tests.test_107cup_preview_deploy_contract",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "current.next",
            'mv -Tf "$root/current.next"',
            'printf \'%s\\n\' "$commit" > "$root/runtime/build-commit"',
        ):
            self.assertNotIn(forbidden, source)

    def test_stable_build_explicitly_selects_live_data(self):
        source = self.read_required("build.slurm")
        self.assertIn("VITE_LMATELAB_EDITION=107cup", source)
        self.assertIn("VITE_COMPETITION_DATA_MODE=live", source)

    def test_preview_service_uses_private_data_runtime_and_port(self):
        source = self.read_required("preview-service.slurm")
        for required in (
            "#SBATCH --time=2-00:00:00",
            "umask 077",
            "preview-runtime",
            "sqlite3",
            ".backup",
            "LMATELAB_RELEASE_KIND=preview",
            "LMATELAB_DATA_MODE=demo",
            "preview-service-port",
            "uvicorn main_107cup:app",
            "--workers 1",
            "alembic -c alembic.ini upgrade head",
            "alembic -c alembic_digest.ini upgrade head",
        ):
            self.assertIn(required, source)
        self.assertNotIn("#SBATCH --gres", source)
        self.assertNotIn('readlink -f "$root/current"', source)
        self.assertNotIn(
            "DATABASE_URL=sqlite:////home/scc/pb23030683/lmatelab-107cup/data/db/eln.db",
            source,
        )

    def test_preview_service_overrides_every_writable_path_after_runtime_env(self):
        source = self.read_required("preview-service.slurm")
        runtime_source = source.index('source "$runtime_env"')
        for variable in (
            "DATABASE_URL",
            "DIGEST_DATABASE_URL",
            "LMATELAB_DATA_DIR",
            "UPLOADS_ROOT",
            "VASP_UPLOADS_ROOT",
            "VASP_CUSTOM_DB_ROOT",
            "QE_EPW_CUSTOM_DB_ROOT",
            "VASP_ELEMENTS_CACHE_DIR",
            "ISSUES_DIR",
            "CHANGELOG_PATH",
            "ACADEMIC_REPORTS_FILE",
            "MPLCONFIGDIR",
        ):
            assignment = f"export {variable}="
            self.assertIn(assignment, source)
            self.assertGreater(source.index(assignment), runtime_source)

    def test_login_node_helpers_only_fetch_submit_and_verify(self):
        for name in (
            "submit-preview-build.sh",
            "submit-preview-service.sh",
            "submit-preview-snapshot.sh",
            "verify-preview-runtime.sh",
        ):
            source = self.read_required(name)
            for line in source.splitlines():
                command = line.strip()
                for forbidden_prefix in (
                    "npm ci",
                    "npm run build",
                    "pip install",
                    "python -m pip install",
                    "uvicorn ",
                    "exec uvicorn ",
                    "alembic ",
                ):
                    self.assertFalse(command.startswith(forbidden_prefix), line)

        build_submit = self.read_required("submit-preview-build.sh")
        self.assertIn("git -C \"$project\" fetch --quiet origin main", build_submit)
        self.assertIn("sbatch --parsable", build_submit)
        self.assertIn("build-job-id", build_submit)

        service_submit = self.read_required("submit-preview-service.sh")
        self.assertIn("sha256sum -c manifest.sha256", service_submit)
        self.assertIn("last-service-job-id", service_submit)

    def test_preview_runtime_verifier_has_running_and_stopped_gates(self):
        source = self.read_required("verify-preview-runtime.sh")
        for required in (
            "running|stopped",
            "squeue",
            "sacct",
            "sha256sum -c manifest.sha256",
            "/api/health/live",
            "/api/health/ready",
            '"release_kind":"preview"',
            '"data_mode":"demo"',
            "curl --connect-timeout 3",
            "unexpected LMateLab process found on the login node",
        ):
            self.assertIn(required, source)

    def test_preview_runtime_verifier_keeps_scontrol_authoritative_when_sacct_is_unavailable(self):
        source = self.read_required("verify-preview-runtime.sh")
        self.assertIn('scontrol show job "$job_id"', source)
        self.assertIn('if ! sacct -j "$job_id"', source)
        self.assertIn("sacct unavailable; continuing with scontrol evidence", source)

    def test_snapshot_job_compares_stable_state_without_writing_it(self):
        source = self.read_required("preview-snapshot.slurm")
        for required in (
            "LMATELAB_PREVIEW_SNAPSHOT_PHASE",
            "LMATELAB_PREVIEW_BEFORE_DIR",
            "before|after",
            "current-target.txt",
            "stable-eln.sha256",
            "stable-digests.sha256",
            "stable-eln-integrity.txt",
            "stable-digests-integrity.txt",
            "stable-service-job-id.txt",
            "stable-service-node.txt",
            "stable-service-port.txt",
            "stable-service-commit.txt",
            "stable-health-live.json",
            "cmp",
            "manifest.sha256",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "sqlite3 \"$root/data/db/eln.db\" .backup",
            "sqlite3 \"$root/data/db/digests.db\" .backup",
            'mv -Tf "$root/current.next"',
            "scancel",
        ):
            self.assertNotIn(forbidden, source)

    def test_snapshot_preserves_sacct_failure_without_losing_stable_state_evidence(self):
        source = self.read_required("preview-snapshot.slurm")
        self.assertIn(
            'scontrol show job "$stable_job_id" > "$evidence/scontrol.txt"',
            source,
        )
        self.assertIn('if ! sacct -j "$stable_job_id"', source)
        self.assertIn('2> "$evidence/sacct.stderr.txt"', source)
        self.assertIn('> "$evidence/sacct-status.txt"', source)

    def test_runtime_example_declares_stable_live_identity(self):
        source = self.read_required("runtime.env.example")
        self.assertIn("LMATELAB_RELEASE_KIND=stable", source)
        self.assertIn("LMATELAB_DATA_MODE=live", source)


if __name__ == "__main__":
    unittest.main()
