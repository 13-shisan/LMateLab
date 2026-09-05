from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


def number(value: str):
    try:
        return float(value) if value else None
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_csv", type=Path)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    with args.source_csv.open(newline="", encoding="utf-8") as source, sqlite3.connect(args.database) as db:
        db.execute("DROP TABLE IF EXISTS structures")
        db.execute("""CREATE TABLE structures (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, name TEXT NOT NULL, formula TEXT NOT NULL,
            topology TEXT, natoms INTEGER, bandgap REAL, energy REAL, doi TEXT
        )""")
        rows = csv.DictReader(source)
        db.executemany(
            "INSERT INTO structures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ((
                row["qmof_id"], "QMOF", row["name"], row["info.formula"],
                row["info.mofid.topology"], int(row["info.natoms"]) if row["info.natoms"] else None,
                number(row["outputs.pbe.bandgap"]), number(row["outputs.pbe.energy_total"]), row["info.doi"],
            ) for row in rows),
        )
        db.execute("CREATE INDEX ix_structures_formula ON structures(formula)")
        db.execute("CREATE INDEX ix_structures_name ON structures(name)")
        count = db.execute("SELECT COUNT(*) FROM structures").fetchone()[0]
    args.database.chmod(0o600)
    print(f"imported {count} QMOF structures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
