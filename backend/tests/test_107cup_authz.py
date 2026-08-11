import importlib.util
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class CompetitionAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module_path = BACKEND_ROOT / "competition_authz.py"

    def load_authz(self):
        self.assertTrue(self.module_path.is_file(), str(self.module_path))
        if not self.module_path.is_file():
            return None
        spec = importlib.util.spec_from_file_location("competition_authz", self.module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_role_dependencies_reject_legacy_and_unapproved_roles(self):
        authz = self.load_authz()
        if authz is None:
            return

        operator = SimpleNamespace(role="operator")
        viewer = SimpleNamespace(role="viewer")
        self.assertIs(operator, authz.require_operator(operator))
        self.assertIs(operator, authz.require_viewer_or_operator(operator))
        self.assertIs(viewer, authz.require_viewer_or_operator(viewer))

        for role in ("root", "user", "", "administrator"):
            with self.subTest(role=role):
                with self.assertRaises(HTTPException) as raised:
                    authz.require_viewer_or_operator(SimpleNamespace(role=role))
                self.assertEqual(403, raised.exception.status_code)

        with self.assertRaises(HTTPException) as raised:
            authz.require_operator(viewer)
        self.assertEqual(403, raised.exception.status_code)

    def test_missing_bearer_credentials_return_401(self):
        import auth_identity

        with self.assertRaises(HTTPException) as raised:
            auth_identity.get_current_user(None, None)
        self.assertEqual(401, raised.exception.status_code)

    def test_viewer_business_writes_are_forbidden(self):
        authz = self.load_authz()
        if authz is None:
            return

        viewer = SimpleNamespace(role="viewer")
        operator = SimpleNamespace(role="operator")
        get_request = SimpleNamespace(method="GET")
        post_request = SimpleNamespace(method="POST")

        self.assertIs(viewer, authz.require_business_access(get_request, viewer))
        self.assertIs(operator, authz.require_business_access(post_request, operator))
        with self.assertRaises(HTTPException) as raised:
            authz.require_business_access(post_request, viewer)
        self.assertEqual(403, raised.exception.status_code)

    def test_competition_account_changes_and_legacy_login_fail_closed(self):
        authz = self.load_authz()
        if authz is None:
            return

        competition_env = {"LMATELAB_EDITION": "107cup"}
        with self.assertRaises(HTTPException) as raised:
            authz.require_account_changes_enabled(competition_env)
        self.assertEqual(403, raised.exception.status_code)

        with self.assertRaises(HTTPException) as raised:
            authz.require_competition_role(
                SimpleNamespace(role="root"),
                competition_env,
            )
        self.assertEqual(403, raised.exception.status_code)

        viewer = SimpleNamespace(role="viewer")
        self.assertIs(viewer, authz.require_competition_role(viewer, competition_env))


class CompetitionRoleMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script_path = REPO_ROOT / "deploy" / "107cup" / "migrate-competition-roles.py"

    def assert_posix_mode(self, path: Path, expected: int):
        if os.name != "nt":
            self.assertEqual(expected, stat.S_IMODE(path.stat().st_mode))

    def load_migration(self):
        self.assertTrue(self.script_path.is_file(), str(self.script_path))
        if not self.script_path.is_file():
            return None
        spec = importlib.util.spec_from_file_location("migrate_competition_roles", self.script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def create_database(path: Path):
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, "
            "password_hash TEXT NOT NULL, name TEXT NOT NULL UNIQUE, "
            "alias TEXT NOT NULL, role TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO users (email, password_hash, name, alias, role) "
            "VALUES (?, ?, ?, ?, ?)",
            ("operator@example.invalid", "unchanged-password-hash", "107杯管理员", "pb23030683", "root"),
        )
        connection.commit()
        connection.close()

    def test_root_to_operator_migration_is_backed_up_and_idempotent(self):
        migration = self.load_migration()
        if migration is None:
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "eln.db"
            backups = root / "backups"
            self.create_database(database)

            open_calls = []
            real_open = migration.os.open

            def record_open(path, flags, mode=0o777):
                open_calls.append((Path(path), flags, mode))
                return real_open(path, flags, mode)

            with mock.patch.object(migration.os, "open", side_effect=record_open):
                first = migration.migrate_database(database, backups, "pb23030683")
            self.assertTrue(first.changed)
            self.assertTrue(first.backup_path.is_file())
            self.assert_posix_mode(backups, 0o700)
            self.assert_posix_mode(first.backup_path, 0o600)
            self.assertEqual(1, len(open_calls))
            _, flags, mode = open_calls[0]
            self.assertTrue(flags & migration.os.O_CREAT)
            self.assertTrue(flags & migration.os.O_EXCL)
            self.assertEqual(0o600, mode)

            with closing(sqlite3.connect(first.backup_path)) as backup_connection:
                backup_role = backup_connection.execute(
                    "SELECT role FROM users WHERE alias = ?", ("pb23030683",)
                ).fetchone()[0]
            self.assertEqual("root", backup_role)

            with closing(sqlite3.connect(database)) as connection:
                migrated = connection.execute(
                    "SELECT role, password_hash FROM users WHERE alias = ?", ("pb23030683",)
                ).fetchone()
                user_count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            self.assertEqual(("operator", "unchanged-password-hash"), migrated)
            self.assertEqual(1, user_count)

            second = migration.migrate_database(database, backups, "pb23030683")
            self.assertFalse(second.changed)
            self.assertIsNone(second.backup_path)
            self.assertEqual(1, len(list(backups.glob("eln.db.before-competition-roles.*.sqlite"))))

            with closing(sqlite3.connect(database)) as connection:
                repeated = connection.execute(
                    "SELECT role, password_hash FROM users WHERE alias = ?", ("pb23030683",)
                ).fetchone()
                repeated_count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            self.assertEqual(("operator", "unchanged-password-hash"), repeated)
            self.assertEqual(1, repeated_count)

    def test_existing_backup_name_is_not_overwritten_or_migrated(self):
        migration = self.load_migration()
        if migration is None:
            return

        class FixedDateTime:
            @classmethod
            def now(cls, tz):
                return datetime(2026, 8, 6, 2, 0, 0, tzinfo=timezone.utc).astimezone(tz)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "eln.db"
            backups = root / "backups"
            self.create_database(database)
            backups.mkdir(mode=0o700)
            collision = backups / "eln.db.before-competition-roles.20260806T020000000000Z.sqlite"
            collision.write_bytes(b"existing-evidence")

            with mock.patch.object(migration, "datetime", FixedDateTime):
                with self.assertRaises(FileExistsError):
                    migration.migrate_database(database, backups, "pb23030683")

            self.assertEqual(b"existing-evidence", collision.read_bytes())
            with closing(sqlite3.connect(database)) as connection:
                role, password_hash = connection.execute(
                    "SELECT role, password_hash FROM users WHERE alias = ?", ("pb23030683",)
                ).fetchone()
            self.assertEqual(("root", "unchanged-password-hash"), (role, password_hash))

    def test_failed_role_update_rolls_back_and_preserves_backup(self):
        migration = self.load_migration()
        if migration is None:
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "eln.db"
            backups = root / "backups"
            self.create_database(database)
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "CREATE TRIGGER reject_role_update BEFORE UPDATE OF role ON users "
                    "BEGIN SELECT RAISE(ABORT, 'blocked update'); END"
                )
                connection.commit()

            with self.assertRaises(sqlite3.IntegrityError):
                migration.migrate_database(database, backups, "pb23030683")

            backup_files = list(backups.glob("eln.db.before-competition-roles.*.sqlite"))
            self.assertEqual(1, len(backup_files))
            self.assert_posix_mode(backup_files[0], 0o600)
            with closing(sqlite3.connect(backup_files[0])) as backup_connection:
                backup_role = backup_connection.execute(
                    "SELECT role FROM users WHERE alias = ?", ("pb23030683",)
                ).fetchone()[0]
            with closing(sqlite3.connect(database)) as connection:
                current = connection.execute(
                    "SELECT role, password_hash FROM users WHERE alias = ?", ("pb23030683",)
                ).fetchone()
            self.assertEqual("root", backup_role)
            self.assertEqual(("root", "unchanged-password-hash"), current)


if __name__ == "__main__":
    unittest.main()
