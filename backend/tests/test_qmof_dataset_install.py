from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from scripts.import_qmof_structure_index import QmofIndexError, import_index
from scripts.install_qmof_dataset import (
    QMOF_V18,
    QmofInstallError,
    install_dataset,
)


CSV_FIELDS = (
    "qmof_id",
    "name",
    "info.formula",
    "info.mofid.topology",
    "info.natoms",
    "outputs.pbe.bandgap",
    "outputs.pbe.energy_total",
    "info.doi",
)


def _digest(content: bytes, algorithm: str) -> str:
    return hashlib.new(algorithm, content).hexdigest()


def _csv_content(ids: list[str], *, bandgap: str = "1.25") -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for index, structure_id in enumerate(ids, start=1):
        writer.writerow(
            {
                "qmof_id": structure_id,
                "name": f"TEST_{index}",
                "info.formula": "Cu2C4H4O8",
                "info.mofid.topology": "pcu",
                "info.natoms": "18",
                "outputs.pbe.bandgap": bandgap,
                "outputs.pbe.energy_total": "-42.5",
                "info.doi": "https://doi.org/10.0000/example",
            }
        )
    return output.getvalue().encode("utf-8")


def _archive_fixture(
    root: Path,
    *,
    csv_ids: list[str] | None = None,
    cif_ids: list[str] | None = None,
    unsafe_outer_member: str | None = None,
) -> tuple[Path, object]:
    csv_ids = csv_ids or ["qmof-0000001", "qmof-0000002"]
    cif_ids = cif_ids or list(csv_ids)
    csv_bytes = _csv_content(csv_ids)
    inner_buffer = io.BytesIO()
    cif_bytes = 0
    with zipfile.ZipFile(inner_buffer, "w", compression=zipfile.ZIP_DEFLATED) as inner:
        for structure_id in cif_ids:
            content = f"data_{structure_id}\n_cell_length_a 1\n".encode("ascii")
            cif_bytes += len(content)
            inner.writestr(f"relaxed_structures/{structure_id}.cif", content)
    inner_bytes = inner_buffer.getvalue()
    archive = root / "qmof_database.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as outer:
        outer.writestr(QMOF_V18.csv_member, csv_bytes)
        outer.writestr(QMOF_V18.cif_archive_member, inner_bytes)
        if unsafe_outer_member:
            outer.writestr(unsafe_outer_member, b"unsafe")
    archive_bytes = archive.read_bytes()
    spec = replace(
        QMOF_V18,
        archive_size=len(archive_bytes),
        archive_md5=_digest(archive_bytes, "md5"),
        archive_sha256=_digest(archive_bytes, "sha256"),
        csv_size=len(csv_bytes),
        csv_sha256=_digest(csv_bytes, "sha256"),
        cif_archive_size=len(inner_bytes),
        cif_archive_sha256=_digest(inner_bytes, "sha256"),
        expected_count=len(csv_ids),
        expected_cif_bytes=cif_bytes,
    )
    return archive, spec


class QmofDatasetInstallTests(unittest.TestCase):
    def test_installs_verified_index_and_cifs_then_reuses_the_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, spec = _archive_fixture(root)
            data_root = root / "data"

            result = install_dataset(
                archive,
                data_root,
                spec=spec,
                source_commit="a" * 40,
                transport_url_used="http://222.195.94.37:18757/qmof_database-v18.zip",
                switch_current=False,
            )

            self.assertFalse(result["reused"])
            self.assertEqual(2, result["record_count"])
            version_root = data_root / "v18"
            self.assertEqual(
                ["qmof-0000001.cif", "qmof-0000002.cif"],
                sorted(path.name for path in (version_root / "relaxed_structures").iterdir()),
            )
            with sqlite3.connect(version_root / "structures.sqlite") as connection:
                self.assertEqual(("ok",), connection.execute("PRAGMA integrity_check").fetchone())
                self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM structures").fetchone()[0])
            provenance = json.loads((version_root / "provenance.json").read_text())
            self.assertEqual(spec.doi, provenance["doi"])
            self.assertEqual("a" * 40, provenance["source_commit"])
            self.assertEqual(
                "http://222.195.94.37:18757/qmof_database-v18.zip",
                provenance["transport_url"],
            )
            self.assertIn("Temporary relay", provenance["transport_note"])

            reused = install_dataset(
                archive,
                data_root,
                spec=spec,
                source_commit="b" * 40,
                switch_current=False,
            )
            self.assertTrue(reused["reused"])

    def test_archive_hash_mismatch_fails_without_installing_a_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, spec = _archive_fixture(root)
            invalid_spec = replace(spec, archive_sha256="0" * 64)

            with self.assertRaisesRegex(QmofInstallError, "SHA-256 mismatch"):
                install_dataset(
                    archive,
                    root / "data",
                    spec=invalid_spec,
                    switch_current=False,
                )

            self.assertFalse((root / "data" / "v18").exists())

    def test_path_traversal_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, spec = _archive_fixture(root, unsafe_outer_member="../escape.txt")

            with self.assertRaisesRegex(QmofInstallError, "unsafe ZIP member"):
                install_dataset(
                    archive,
                    root / "data",
                    spec=spec,
                    switch_current=False,
                )

            self.assertFalse((root / "escape.txt").exists())
            self.assertFalse((root / "data" / "v18").exists())

    def test_csv_and_cif_id_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, spec = _archive_fixture(
                root,
                csv_ids=["qmof-0000001", "qmof-0000002"],
                cif_ids=["qmof-0000001", "qmof-0000003"],
            )

            with self.assertRaisesRegex(QmofInstallError, "CSV and CIF ID sets differ"):
                install_dataset(
                    archive,
                    root / "data",
                    spec=spec,
                    switch_current=False,
                )

            self.assertFalse((root / "data" / "v18").exists())

    def test_index_import_rejects_nonfinite_data_without_replacing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "qmof.csv"
            source.write_bytes(_csv_content(["qmof-0000001"], bandgap="nan"))
            database = root / "structures.sqlite"
            database.write_bytes(b"preserve-me")

            with self.assertRaisesRegex(QmofIndexError, "not finite"):
                import_index(source, database, expected_count=1)

            self.assertEqual(b"preserve-me", database.read_bytes())
            self.assertEqual([], list(root.glob(".structures.sqlite.*.tmp")))

    def test_107_deploy_contract_runs_only_through_slurm_and_wires_both_processes(self):
        root = Path(__file__).resolve().parents[2]
        slurm = (root / "deploy/107cup/qmof-library.slurm").read_text()
        submit = (root / "deploy/107cup/submit-qmof-library.sh").read_text()
        runtime = (root / "deploy/107cup/runtime.env.example").read_text()
        service = (root / "deploy/107cup/service.slurm").read_text()
        worker = (root / "deploy/107cup/agent-worker.slurm").read_text()
        build = (root / "deploy/107cup/build.slurm").read_text()

        for required in (
            "#SBATCH --account=competition",
            "#SBATCH --partition=P107-A100",
            "#SBATCH --qos=qos_p107-a100",
            "#SBATCH --cpus-per-task=1",
            "#SBATCH --mem=8G",
            "#SBATCH --time=01:00:00",
            "SLURM_JOB_ID",
            "install_qmof_dataset.py",
            "--verify-archive-only",
            "--verify-installed",
            "flock -n",
            "QMOF_INSTALL_OK",
            "LMATELAB_QMOF_TRANSFER_URL",
            "temporary_relay_url",
            "unapproved QMOF transfer URL",
            "--transport-url-used",
            "curl_protocol='=https'",
            "curl_protocol='=http'",
            'curl_tls=(--tlsv1.2)',
            "curl_tls=()",
        ):
            self.assertIn(required, slurm)
        for forbidden in (
            "vasp_std",
            "vasp_gam",
            "vasp_ncl",
            "uvicorn",
            "npm ",
            "pip install",
        ):
            self.assertNotIn(forbidden, slurm)
        self.assertIn("sbatch --parsable", submit)
        self.assertIn('test -z "$(git -C "$project" status --porcelain)"', submit)
        for source in (runtime, service, worker):
            self.assertIn("LMATELAB_STRUCTURE_LIBRARY_DB", source)
            self.assertIn("LMATELAB_QMOF_CIF_ROOT", source)
        self.assertIn(
            "/home/scc/pb23030683/lmatelab-107cup/data/qmof/current", runtime
        )
        for source in (service, worker):
            self.assertIn(
                "$root/data/qmof/current", source
            )
        self.assertIn("tests.test_qmof_dataset_install", build)


if __name__ == "__main__":
    unittest.main()
