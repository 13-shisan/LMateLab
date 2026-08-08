import importlib.util
import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "deploy" / "107cup" / "provision-competition-viewer.py"


class CompetitionViewerProvisionTests(unittest.TestCase):
    def load_provisioner(self):
        self.assertTrue(SCRIPT_PATH.is_file(), str(SCRIPT_PATH))
        if not SCRIPT_PATH.is_file():
            return None
        spec = importlib.util.spec_from_file_location("provision_competition_viewer", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def create_database(path: Path):
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, "
                "password_hash TEXT NOT NULL, name TEXT NOT NULL UNIQUE, "
                "alias TEXT NOT NULL, role TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO users (email, password_hash, name, alias, role) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "operator@example.invalid",
                    "hash:operator-password",
                    "107 Cup Operator",
                    "pb23030683",
                    "operator",
                ),
            )
            connection.commit()

    @staticmethod
    def hash_password(password: str) -> str:
        return f"hash:{password}"

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        return password_hash == f"hash:{password}"

    def test_create_viewer_is_backed_up_and_idempotent_without_password_reset(self):
        provisioner = self.load_provisioner()
        if provisioner is None:
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "eln.db"
            backups = root / "backups"
            self.create_database(database)
            open_calls = []
            real_open = provisioner.os.open

            def record_open(path, flags, mode=0o777):
                open_calls.append((Path(path), flags, mode))
                return real_open(path, flags, mode)

            with mock.patch.object(provisioner.os, "open", side_effect=record_open):
                first = provisioner.provision_viewer(
                    database,
                    backups,
                    email="viewer@lmatelab.invalid",
                    name="107 Cup Demo Viewer",
                    alias="demo-viewer",
                    password="viewer-password-long-enough",
                    hash_password=self.hash_password,
                    verify_password=self.verify_password,
                )

            self.assertTrue(first.created)
            self.assertTrue(first.backup_path.is_file())
            self.assertEqual(1, len(open_calls))
            _, flags, mode = open_calls[0]
            self.assertTrue(flags & os.O_CREAT)
            self.assertTrue(flags & os.O_EXCL)
            self.assertEqual(0o600, mode)

            with closing(sqlite3.connect(database)) as connection:
                created = connection.execute(
                    "SELECT email, name, alias, role, password_hash FROM users "
                    "WHERE alias = ?",
                    ("demo-viewer",),
                ).fetchone()
            self.assertEqual(
                (
                    "viewer@lmatelab.invalid",
                    "107 Cup Demo Viewer",
                    "demo-viewer",
                    "viewer",
                    "hash:viewer-password-long-enough",
                ),
                created,
            )

            second = provisioner.provision_viewer(
                database,
                backups,
                email="VIEWER@LMATELAB.INVALID",
                name="107 Cup Demo Viewer",
                alias="demo-viewer",
                password="viewer-password-long-enough",
                hash_password=self.hash_password,
                verify_password=self.verify_password,
            )
            self.assertFalse(second.created)
            self.assertIsNone(second.backup_path)
            self.assertEqual(1, len(list(backups.glob("eln.db.before-viewer.*.sqlite"))))

    def test_conflict_or_password_mismatch_never_changes_existing_account(self):
        provisioner = self.load_provisioner()
        if provisioner is None:
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "eln.db"
            backups = root / "backups"
            self.create_database(database)

            first = provisioner.provision_viewer(
                database,
                backups,
                email="viewer@lmatelab.invalid",
                name="107 Cup Demo Viewer",
                alias="demo-viewer",
                password="viewer-password-long-enough",
                hash_password=self.hash_password,
                verify_password=self.verify_password,
            )
            self.assertTrue(first.created)

            with self.assertRaises(RuntimeError):
                provisioner.provision_viewer(
                    database,
                    backups,
                    email="viewer@lmatelab.invalid",
                    name="107 Cup Demo Viewer",
                    alias="demo-viewer",
                    password="different-viewer-password",
                    hash_password=self.hash_password,
                    verify_password=self.verify_password,
                )
            with self.assertRaises(RuntimeError):
                provisioner.provision_viewer(
                    database,
                    backups,
                    email="other@lmatelab.invalid",
                    name="Different Viewer",
                    alias="demo-viewer",
                    password="viewer-password-long-enough",
                    hash_password=self.hash_password,
                    verify_password=self.verify_password,
                )

            with closing(sqlite3.connect(database)) as connection:
                current = connection.execute(
                    "SELECT email, name, alias, role, password_hash FROM users "
                    "WHERE alias = ?",
                    ("demo-viewer",),
                ).fetchone()
            self.assertEqual(
                (
                    "viewer@lmatelab.invalid",
                    "107 Cup Demo Viewer",
                    "demo-viewer",
                    "viewer",
                    "hash:viewer-password-long-enough",
                ),
                current,
            )
            self.assertEqual(1, len(list(backups.glob("eln.db.before-viewer.*.sqlite"))))

    def test_password_file_must_be_private_regular_and_owned(self):
        provisioner = self.load_provisioner()
        if provisioner is None:
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            password_file = Path(temp_dir) / "demo-viewer.password"
            password_file.write_text("viewer-password-long-enough\n", encoding="utf-8")

            private = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=1234)
            with mock.patch.object(provisioner.os, "getuid", return_value=1234, create=True), \
                    mock.patch.object(provisioner.os, "lstat", return_value=private):
                self.assertEqual(
                    "viewer-password-long-enough",
                    provisioner.read_private_password(password_file),
                )

            permissive = SimpleNamespace(st_mode=stat.S_IFREG | 0o640, st_uid=1234)
            with mock.patch.object(provisioner.os, "getuid", return_value=1234, create=True), \
                    mock.patch.object(provisioner.os, "lstat", return_value=permissive):
                with self.assertRaises(PermissionError):
                    provisioner.read_private_password(password_file)

            symlink = SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=1234)
            with mock.patch.object(provisioner.os, "getuid", return_value=1234, create=True), \
                    mock.patch.object(provisioner.os, "lstat", return_value=symlink):
                with self.assertRaises(PermissionError):
                    provisioner.read_private_password(password_file)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_database_path_must_not_be_a_symbolic_link(self):
        provisioner = self.load_provisioner()
        if provisioner is None:
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "eln.db"
            database_link = root / "eln-link.db"
            self.create_database(database)
            try:
                database_link.symlink_to(database)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            with self.assertRaises(PermissionError):
                provisioner.provision_viewer(
                    database_link,
                    root / "backups",
                    email="viewer@lmatelab.invalid",
                    name="107 Cup Demo Viewer",
                    alias="demo-viewer",
                    password="viewer-password-long-enough",
                    hash_password=self.hash_password,
                    verify_password=self.verify_password,
                )


if __name__ == "__main__":
    unittest.main()
