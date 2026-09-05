import csv
import hashlib
import re
import unittest
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
SLURM = ROOT / "deploy" / "107cup" / "slurm" / "stage10-acceptance.slurm"
HARNESS = ROOT / "deploy" / "107cup" / "slurm" / "stage10-acceptance.py"
SUBMIT = ROOT / "deploy" / "107cup" / "submit-stage10-acceptance.sh"
GENERATOR = ROOT / "deploy" / "107cup" / "generate-stage10-manifest.py"
RUNTIME_VERIFY = ROOT / "deploy" / "107cup" / "verify-runtime.sh"
DELIVERY_DOCS = (
    ROOT / "docs" / "107cup" / "deployment.md",
    ROOT / "docs" / "107cup" / "data-and-provenance.md",
    ROOT / "docs" / "107cup" / "compute-cluster-run-data.md",
    ROOT / "docs" / "107cup" / "demo-script.md",
    ROOT / "docs" / "107cup" / "final-acceptance.md",
)
MANIFEST = ROOT / "docs" / "107cup" / "artifacts" / "manifest.sha256"
SLURM_LEDGER = ROOT / "docs" / "107cup" / "artifacts" / "slurm-job-ledger.csv"
SLURM_LOG_ARCHIVE = (
    ROOT
    / "docs"
    / "107cup"
    / "artifacts"
    / "lmatelab-107cup-compute-cluster-run-data-20260905.zip"
)
SLURM_LOG_ARCHIVE_SHA256 = Path(f"{SLURM_LOG_ARCHIVE}.sha256")
EXPECTED_SLURM_LOG_ARCHIVE_SHA256 = (
    "17db1b8646239cec4881a3e2ba93bca4b5acd7b51eeb89c7bd9b930dc36bf997"
)


class Stage10DeliveryContractTests(unittest.TestCase):
    @staticmethod
    def canonical_text_digest(path: Path) -> str:
        content = path.read_bytes()
        text = content.decode("utf-8")
        canonical = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

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

    def test_runtime_checks_use_the_fixed_compute_network_not_login_node_dns(self):
        harness = HARNESS.read_text(encoding="utf-8")
        verifier = RUNTIME_VERIFY.read_text(encoding="utf-8")
        self.assertIn("def _node_to_address", harness)
        self.assertIn('return f"11.11.10.{number}"', harness)
        self.assertIn("node_address=$(printf '11.11.10.%d'", verifier)
        self.assertIn('http://$node_address:$port/api/health/live', verifier)
        self.assertNotIn('http://$node:$port/api/health/live', verifier)

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
        self.assertIn('replace("\\r\\n", "\\n").replace("\\r", "\\n")', source)
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
            self.assertEqual(digest, self.canonical_text_digest(path), relative)

    def test_slurm_ledger_has_remote_absolute_and_portable_attachment_paths(self):
        with SLURM_LEDGER.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 218)
        self.assertEqual(len({row["job_id"] for row in rows}), 218)
        for row in rows:
            remote_paths = row["remote_evidence_files"].split(";")
            self.assertTrue(remote_paths, row["job_id"])
            for path in remote_paths:
                self.assertTrue(
                    path.startswith("/home/scc/pb23030683/lmatelab-107cup/"),
                    (row["job_id"], path),
                )

            attachment_paths = row["attachment_files"].split(";")
            for path in attachment_paths:
                if path == "unavailable":
                    continue
                pure = PurePosixPath(path)
                self.assertFalse(pure.is_absolute(), (row["job_id"], path))
                self.assertNotIn("..", pure.parts, (row["job_id"], path))
                self.assertNotIn("\\", path, (row["job_id"], path))

    def test_slurm_log_archive_is_complete_and_hash_verified(self):
        self.assertTrue(SLURM_LOG_ARCHIVE.is_file())
        self.assertEqual(
            SLURM_LOG_ARCHIVE_SHA256.read_text(encoding="ascii").strip(),
            f"{EXPECTED_SLURM_LOG_ARCHIVE_SHA256}  {SLURM_LOG_ARCHIVE.name}",
        )
        self.assertEqual(
            hashlib.sha256(SLURM_LOG_ARCHIVE.read_bytes()).hexdigest(),
            EXPECTED_SLURM_LOG_ARCHIVE_SHA256,
        )

        with zipfile.ZipFile(SLURM_LOG_ARCHIVE) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            self.assertEqual(len(files), 563)
            self.assertEqual(sum(item.file_size for item in files), 16_981_635)
            names = {item.filename for item in files}
            self.assertTrue(
                all(name.startswith("submission-attachment/") for name in names)
            )
            forbidden = re.compile(
                r"(^|/)(POTCAR|OUTCAR|WAVECAR|CHGCAR|\.env(?:\..*)?|"
                r"[^/]+\.(?:db|sqlite|sqlite3|pem|key|p12|pfx))$",
                re.IGNORECASE,
            )
            self.assertFalse([name for name in names if forbidden.search(name)])

            checksum_member = "submission-attachment/SHA256SUMS.txt"
            checksum_lines = archive.read(checksum_member).decode("ascii").splitlines()
            self.assertEqual(len(checksum_lines), 562)
            for line in checksum_lines:
                match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_./-]+)", line)
                self.assertIsNotNone(match, line)
                digest, relative = match.groups()
                member = f"submission-attachment/{relative}"
                self.assertIn(member, names)
                self.assertEqual(digest, hashlib.sha256(archive.read(member)).hexdigest())


if __name__ == "__main__":
    unittest.main()
