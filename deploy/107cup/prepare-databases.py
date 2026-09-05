#!/usr/bin/env python3
"""Create consistent pre-migration backups and verify the 107 Cup databases."""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import stat
from pathlib import Path


ROOT = Path("/home/scc/pb23030683/lmatelab-107cup")
DATA_ROOT = ROOT / "data" / "db"
BACKUP_ROOT = ROOT / "backups"
SAFE_LABEL = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class DatabasePreparationError(RuntimeError):
    pass


def _within(path: Path, parent: Path) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(parent.resolve(strict=False))
    except ValueError as exc:
        raise DatabasePreparationError(f"path escapes {parent}: {path}") from exc
    return resolved


def _regular_database(path: Path, *, required: bool) -> Path | None:
    path = _within(path, DATA_ROOT)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if required:
            raise DatabasePreparationError(f"database is missing: {path}")
        return None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise DatabasePreparationError(f"database is not a regular file: {path}")
    return path


def verify_database(path: Path, *, required: bool = True) -> bool:
    source = _regular_database(path, required=required)
    if source is None:
        return False
    connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if result != ("ok",):
        raise DatabasePreparationError(f"database integrity check failed: {source}")
    return True


def backup_database(path: Path, backup_dir: Path, label: str) -> Path | None:
    source_path = _regular_database(path, required=False)
    if source_path is None:
        return None
    if not SAFE_LABEL.fullmatch(label):
        raise DatabasePreparationError("invalid backup label")
    backup_dir = _within(backup_dir, BACKUP_ROOT)
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_dir.chmod(0o700)
    destination_path = backup_dir / f"{source_path.name}.{label}.sqlite"
    descriptor = os.open(destination_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30)
        destination = sqlite3.connect(destination_path, timeout=30)
        try:
            if source.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise DatabasePreparationError(
                    f"source database integrity check failed: {source_path}"
                )
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        destination_path.chmod(0o600)
        verify_backup = sqlite3.connect(
            f"file:{destination_path}?mode=ro", uri=True, timeout=30
        )
        try:
            if verify_backup.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise DatabasePreparationError(
                    f"backup database integrity check failed: {destination_path}"
                )
        finally:
            verify_backup.close()
        return destination_path
    except BaseException:
        destination_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--database", action="append", type=Path, required=True)
    backup_parser.add_argument("--backup-dir", type=Path, required=True)
    backup_parser.add_argument("--label", required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--database", action="append", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "backup":
        for database in args.database:
            destination = backup_database(database, args.backup_dir, args.label)
            if destination is not None:
                print(destination)
        return 0
    for database in args.database:
        verify_database(database)
        print(database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
