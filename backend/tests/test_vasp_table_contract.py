import os
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.vasp_table_schema import (
    DEFAULT_VASP_COLUMNS,
    build_relax_ids_sqlite,
    build_filtered_cache_identity,
    column_metadata,
    order_ids,
    search_formula_ids,
    summarize_database_refs,
)


class VaspTableContractTests(unittest.TestCase):
    def test_default_columns_have_readable_metadata(self):
        metadata = column_metadata(DEFAULT_VASP_COLUMNS)

        self.assertEqual("化学式", metadata["formula"]["label"])
        self.assertEqual("eV", metadata["energy"]["unit"])
        self.assertEqual(4, metadata["fmax"]["decimals"])
        self.assertEqual("计算目录", metadata["data.source_dir"]["label"])

    def test_filtered_cache_identity_includes_row_filters_and_query(self):
        base = build_filtered_cache_identity(
            dbpath="/tmp/example.db",
            only_last=1,
            elem_mode="at_least",
            selected=["Mo", "S"],
            cp_filters=[],
            row_filters=[],
            query="",
        )
        with_row_filter = build_filtered_cache_identity(
            dbpath="/tmp/example.db",
            only_last=1,
            elem_mode="at_least",
            selected=["Mo", "S"],
            cp_filters=[],
            row_filters=[{"col": "formula", "op": "eq", "value": "MoS2"}],
            query="",
        )
        with_query = build_filtered_cache_identity(
            dbpath="/tmp/example.db",
            only_last=1,
            elem_mode="at_least",
            selected=["Mo", "S"],
            cp_filters=[],
            row_filters=[],
            query="MoS2",
        )

        self.assertNotEqual(base, with_row_filter)
        self.assertNotEqual(base, with_query)

    def test_order_ids_supports_newest_and_oldest(self):
        self.assertEqual([9, 4, 1], order_ids([4, 1, 9], "desc"))
        self.assertEqual([1, 4, 9], order_ids([4, 1, 9], "asc"))

    def test_formula_search_is_case_insensitive_and_supports_numeric_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ase.db"
            con = sqlite3.connect(db_path)
            con.execute("create table systems (id integer primary key, formula text)")
            con.executemany(
                "insert into systems(id, formula) values (?, ?)",
                [(1, "MoS2"), (2, "MoSe2"), (3, "RuO2")],
            )
            con.commit()
            con.close()

            self.assertEqual([1, 2], search_formula_ids(str(db_path), "mo"))
            self.assertEqual([3], search_formula_ids(str(db_path), "3"))

    def test_relax_ids_use_final_step_per_source_without_ase_row_scan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ase.db"
            connection = sqlite3.connect(db_path)
            connection.execute("create table systems (id integer primary key, data blob)")

            def ase_blob(source_dir, step_index):
                payload = json.dumps({"source_dir": source_dir, "step_index": step_index}).encode("utf-8")
                return b"\x08\x00\x00\x00\x00\x00\x00\x00" + payload

            connection.executemany(
                "insert into systems(id, data) values (?, ?)",
                [
                    (1, ase_blob("/calc/a", 0)),
                    (2, ase_blob("/calc/a", 2)),
                    (3, ase_blob("/calc/a", 1)),
                    (4, ase_blob("/calc/b", 5)),
                    (5, ase_blob("/calc/b", 5)),
                    (6, ase_blob(None, 9)),
                ],
            )
            connection.commit()
            connection.close()

            self.assertEqual([2, 4], build_relax_ids_sqlite(str(db_path)))

    def test_owner_summary_uses_real_files_and_reports_staleness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "owner.db"
            existing.write_bytes(b"db")
            os.utime(existing, (1000, 1000))
            refs = [
                SimpleNamespace(
                    kind="personal",
                    key="personal:jbwu:owner.db",
                    dbname="owner.db",
                    dbpath=existing,
                    exists=True,
                    missingReason=None,
                ),
                SimpleNamespace(
                    kind="upload",
                    key="upload:jbwu:uploads.db",
                    dbname="uploads.db",
                    dbpath=Path(tmpdir) / "missing.db",
                    exists=False,
                    missingReason="upload database not found",
                ),
            ]

            summary = summarize_database_refs(refs, now_timestamp=1000 + 40 * 86400, stale_days=30)

            self.assertTrue(summary["exists"])
            self.assertTrue(summary["stale"])
            self.assertEqual(2, len(summary["sources"]))


if __name__ == "__main__":
    unittest.main()
