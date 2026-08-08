#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple


class ProvisionResult(NamedTuple):
    created: bool
    user_id: int
    backup_path: Path | None
    email_updated: bool = False


class ExistingViewer(NamedTuple):
    user_id: int
    email_needs_update: bool


LEGACY_VIEWER_EMAIL = "viewer@lmatelab.invalid"
VIEWER_EMAIL = "demo-viewer@matflow.top"


def read_private_password(password_file: Path | str) -> str:
    path = Path(password_file)
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode):
        raise PermissionError(f"password file must be a regular file: {path}")
    if metadata.st_uid != os.getuid():
        raise PermissionError(f"password file must be owned by the current user: {path}")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise PermissionError(f"password file mode must be 0600: {path}")
    password = path.read_text(encoding="utf-8").strip()
    if len(password) < 16:
        raise ValueError("viewer password must contain at least 16 characters")
    return password


def _normalize_identity(email: str, name: str, alias: str) -> tuple[str, str, str]:
    normalized_email = email.strip().lower()
    normalized_name = name.strip()
    normalized_alias = alias.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+", normalized_email):
        raise ValueError("viewer email is invalid")
    if not normalized_name:
        raise ValueError("viewer name must not be empty")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,31}", normalized_alias):
        raise ValueError("viewer alias is invalid")
    return normalized_email, normalized_name, normalized_alias


def _matching_users(
    connection: sqlite3.Connection,
    email: str,
    name: str,
    alias: str,
) -> list[tuple]:
    return connection.execute(
        "SELECT id, email, name, alias, role, password_hash FROM users "
        "WHERE lower(email) = ? OR name = ? OR alias = ? ORDER BY id",
        (email, name, alias),
    ).fetchall()


def _existing_viewer(
    rows: list[tuple],
    email: str,
    name: str,
    alias: str,
    password: str,
    verify_password: Callable[[str, str], bool],
) -> ExistingViewer | None:
    if not rows:
        return None
    if len(rows) != 1:
        raise RuntimeError("viewer identity conflicts with multiple existing accounts")
    user_id, current_email, current_name, current_alias, role, password_hash = rows[0]
    normalized_current_email = str(current_email).lower()
    if (current_name, current_alias, role) != (name, alias, "viewer"):
        raise RuntimeError("viewer identity conflicts with an existing account")
    if not verify_password(password, password_hash):
        raise RuntimeError("refusing to reset an existing viewer password")
    if normalized_current_email == email:
        return ExistingViewer(int(user_id), False)
    if normalized_current_email == LEGACY_VIEWER_EMAIL and email == VIEWER_EMAIL:
        return ExistingViewer(int(user_id), True)
    raise RuntimeError("viewer identity conflicts with an existing account")


def _backup_database(
    source: sqlite3.Connection,
    database_path: Path,
    backup_dir: Path,
) -> Path:
    backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    backup_dir.chmod(0o700)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"{database_path.name}.before-viewer.{timestamp}.sqlite"
    file_descriptor = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(file_descriptor)
    with closing(sqlite3.connect(backup_path)) as destination:
        source.backup(destination)
    backup_path.chmod(0o600)
    return backup_path


def provision_viewer(
    database_path: Path | str,
    backup_dir: Path | str,
    *,
    email: str,
    name: str,
    alias: str,
    password: str,
    hash_password: Callable[[str], str],
    verify_password: Callable[[str, str], bool],
) -> ProvisionResult:
    database_input = Path(database_path)
    if database_input.is_symlink():
        raise PermissionError(f"database must not be a symbolic link: {database_input}")
    database = database_input.resolve()
    backups = Path(backup_dir).resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    if len(password) < 16:
        raise ValueError("viewer password must contain at least 16 characters")
    normalized_email, normalized_name, normalized_alias = _normalize_identity(email, name, alias)

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA busy_timeout=5000;")
        rows = _matching_users(
            connection,
            normalized_email,
            normalized_name,
            normalized_alias,
        )
        existing = _existing_viewer(
            rows,
            normalized_email,
            normalized_name,
            normalized_alias,
            password,
            verify_password,
        )
        if existing is not None and not existing.email_needs_update:
            return ProvisionResult(False, existing.user_id, None)

        backup_path = _backup_database(connection, database, backups)
        try:
            connection.execute("BEGIN IMMEDIATE")
            current_rows = _matching_users(
                connection,
                normalized_email,
                normalized_name,
                normalized_alias,
            )
            if existing is not None:
                current = _existing_viewer(
                    current_rows,
                    normalized_email,
                    normalized_name,
                    normalized_alias,
                    password,
                    verify_password,
                )
                if current != existing:
                    raise RuntimeError("viewer identity changed during provisioning")
                updated = connection.execute(
                    "UPDATE users SET email = ? WHERE id = ? AND lower(email) = ?",
                    (
                        normalized_email,
                        existing.user_id,
                        LEGACY_VIEWER_EMAIL,
                    ),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("viewer email migration failed")
                user_id = existing.user_id
                created_account = False
                email_updated = True
            else:
                if current_rows:
                    raise RuntimeError("viewer identity changed during provisioning")
                password_hash = hash_password(password)
                cursor = connection.execute(
                    "INSERT INTO users (email, password_hash, name, alias, role) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        normalized_email,
                        password_hash,
                        normalized_name,
                        normalized_alias,
                        "viewer",
                    ),
                )
                user_id = int(cursor.lastrowid)
                created_account = True
                email_updated = False
            created = connection.execute(
                "SELECT email, name, alias, role, password_hash FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if created is None or created[:4] != (
                    normalized_email,
                    normalized_name,
                    normalized_alias,
                    "viewer",
            ) or not verify_password(password, created[4]):
                raise RuntimeError("viewer provisioning postcondition failed")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return ProvisionResult(created_account, user_id, backup_path, email_updated)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--password-file", required=True, type=Path)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--alias", required=True)
    args = parser.parse_args()

    from passlib.context import CryptContext

    password = read_private_password(args.password_file)
    password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    result = provision_viewer(
        args.database,
        args.backup_dir,
        email=args.email,
        name=args.name,
        alias=args.alias,
        password=password,
        hash_password=password_context.hash,
        verify_password=password_context.verify,
    )
    print(
        json.dumps(
            {
                "created": result.created,
                "user_id": result.user_id,
                "alias": args.alias,
                "role": "viewer",
                "email": args.email.strip().lower(),
                "email_updated": result.email_updated,
                "backup_path": str(result.backup_path) if result.backup_path else None,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
