#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple


class MigrationResult(NamedTuple):
    changed: bool
    backup_path: Path | None


def _load_operator(connection: sqlite3.Connection, operator_alias: str):
    rows = connection.execute(
        "SELECT id, role, password_hash FROM users WHERE alias = ?",
        (operator_alias,),
    ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(
            f"expected exactly one operator account for alias {operator_alias!r}, found {len(rows)}"
        )
    return rows[0]


def _backup_database(
    source: sqlite3.Connection,
    database_path: Path,
    backup_dir: Path,
) -> Path:
    backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    backup_dir.chmod(0o700)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"{database_path.name}.before-competition-roles.{timestamp}.sqlite"
    file_descriptor = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(file_descriptor)
    with closing(sqlite3.connect(backup_path)) as destination:
        source.backup(destination)
    backup_path.chmod(0o600)
    return backup_path


def migrate_database(
    database_path: Path | str,
    backup_dir: Path | str,
    operator_alias: str,
) -> MigrationResult:
    database = Path(database_path).resolve()
    backups = Path(backup_dir).resolve()
    alias = operator_alias.strip()
    if not database.is_file():
        raise FileNotFoundError(database)
    if not alias:
        raise ValueError("operator alias must not be empty")

    with closing(sqlite3.connect(database)) as connection:
        user_id, role, password_hash = _load_operator(connection, alias)
        if role == "operator":
            return MigrationResult(False, None)
        if role != "root":
            raise RuntimeError(f"refusing unexpected source role {role!r} for {alias!r}")

        backup_path = _backup_database(connection, database, backups)
        try:
            connection.execute("BEGIN IMMEDIATE")
            current_id, current_role, current_hash = _load_operator(connection, alias)
            if (current_id, current_role, current_hash) != (user_id, role, password_hash):
                raise RuntimeError("operator account changed during migration")
            cursor = connection.execute(
                "UPDATE users SET role = ? WHERE id = ? AND role = ?",
                ("operator", user_id, "root"),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("operator role update did not affect exactly one row")
            migrated_role, migrated_hash = connection.execute(
                "SELECT role, password_hash FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if migrated_role != "operator" or migrated_hash != password_hash:
                raise RuntimeError("operator migration postcondition failed")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return MigrationResult(True, backup_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--operator-alias", required=True)
    args = parser.parse_args()

    result = migrate_database(args.database, args.backup_dir, args.operator_alias)
    if result.changed:
        print(f"migrated root to operator; backup={result.backup_path}")
    else:
        print("competition roles already migrated; no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
