from __future__ import annotations

import argparse
import csv
import math
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Mapping


REQUIRED_COLUMNS = (
    "qmof_id",
    "name",
    "info.formula",
    "info.mofid.topology",
    "info.natoms",
    "outputs.pbe.bandgap",
    "outputs.pbe.energy_total",
    "info.doi",
)
QMOF_ID_PATTERN = re.compile(r"qmof-[0-9a-f]+")


class QmofIndexError(ValueError):
    pass


def _optional_float(value: str, *, field: str, line: int) -> float | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = float(stripped)
    except ValueError as exc:
        raise QmofIndexError(f"line {line}: {field} is not numeric") from exc
    if not math.isfinite(parsed):
        raise QmofIndexError(f"line {line}: {field} is not finite")
    return parsed


def _optional_integer(value: str, *, field: str, line: int) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = int(stripped)
    except ValueError as exc:
        raise QmofIndexError(f"line {line}: {field} is not an integer") from exc
    if parsed <= 0:
        raise QmofIndexError(f"line {line}: {field} must be positive")
    return parsed


def _normalized_row(row: Mapping[str, str | None], *, line: int) -> tuple[object, ...]:
    structure_id = (row.get("qmof_id") or "").strip()
    if not QMOF_ID_PATTERN.fullmatch(structure_id):
        raise QmofIndexError(f"line {line}: invalid QMOF id")
    name = (row.get("name") or "").strip()
    formula = (row.get("info.formula") or "").strip()
    if not name or not formula:
        raise QmofIndexError(f"line {line}: name and formula are required")
    topology = (row.get("info.mofid.topology") or "").strip() or None
    doi = (row.get("info.doi") or "").strip() or None
    return (
        structure_id,
        "QMOF",
        name,
        formula,
        topology,
        _optional_integer(row.get("info.natoms") or "", field="info.natoms", line=line),
        _optional_float(
            row.get("outputs.pbe.bandgap") or "",
            field="outputs.pbe.bandgap",
            line=line,
        ),
        _optional_float(
            row.get("outputs.pbe.energy_total") or "",
            field="outputs.pbe.energy_total",
            line=line,
        ),
        doi,
    )


def import_index(
    source_csv: Path,
    database: Path,
    *,
    expected_count: int | None = None,
    provenance: Mapping[str, object] | None = None,
) -> int:
    source_csv = source_csv.resolve(strict=True)
    if database.is_symlink():
        raise QmofIndexError("database path must not be a symlink")
    database = database.parent.resolve(strict=False) / database.name
    if expected_count is not None and expected_count <= 0:
        raise QmofIndexError("expected_count must be positive")
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_name(f".{database.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("""CREATE TABLE structures (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, name TEXT NOT NULL, formula TEXT NOT NULL,
            topology TEXT, natoms INTEGER, bandgap REAL, energy REAL, doi TEXT
        )""")
        connection.execute(
            "CREATE TABLE provenance (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        count = 0
        with source_csv.open(newline="", encoding="utf-8") as source:
            rows = csv.DictReader(source)
            missing = sorted(set(REQUIRED_COLUMNS).difference(rows.fieldnames or ()))
            if missing:
                raise QmofIndexError(f"source CSV is missing columns: {', '.join(missing)}")
            for line, row in enumerate(rows, start=2):
                values = _normalized_row(row, line=line)
                try:
                    connection.execute(
                        "INSERT INTO structures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", values
                    )
                except sqlite3.IntegrityError as exc:
                    raise QmofIndexError(f"line {line}: duplicate QMOF id {values[0]}") from exc
                count += 1
        if expected_count is not None and count != expected_count:
            raise QmofIndexError(
                f"record count mismatch: expected {expected_count}, found {count}"
            )
        metadata = {
            **{str(key): str(value) for key, value in (provenance or {}).items()},
            "schema": "lmatelab-qmof-structure-index-v1",
            "record_count": str(count),
        }
        connection.executemany(
            "INSERT INTO provenance (key, value) VALUES (?, ?)", sorted(metadata.items())
        )
        connection.execute("CREATE INDEX ix_structures_formula ON structures(formula)")
        connection.execute("CREATE INDEX ix_structures_name ON structures(name)")
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise QmofIndexError(f"SQLite integrity check failed: {integrity!r}")
        stored_count = connection.execute("SELECT COUNT(*) FROM structures").fetchone()[0]
        if stored_count != count:
            raise QmofIndexError("SQLite row count changed during import")
        connection.close()
        connection = None
        temporary.chmod(0o600)
        os.replace(temporary, database)
        database.chmod(0o600)
        return count
    except BaseException:
        if connection is not None:
            connection.close()
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_csv", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("--expected-count", type=int)
    args = parser.parse_args()
    count = import_index(
        args.source_csv,
        args.database,
        expected_count=args.expected_count,
    )
    print(f"imported {count} QMOF structures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
