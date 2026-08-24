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
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("JWT_SECRET", "test-only-107cup-auth-secret")
os.environ.setdefault(
    "SECURITY_POLICY_PATH",
    str(REPO_ROOT / "deploy" / "107cup" / "security_policy.json"),
)


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


class CompetitionPasswordChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import auth
        import auth_identity
        import schemas

        cls.auth = auth
        cls.auth_identity = auth_identity
        cls.schemas = schemas
        cls.secret = os.environ["JWT_SECRET"]

    @staticmethod
    def user(password_hash="hash:CurrentPassword1!"):
        return SimpleNamespace(
            id=7,
            email="operator@example.com",
            name="Operator",
            alias="operator",
            role="operator",
            password_hash=password_hash,
        )

    @staticmethod
    def database_for(user):
        query = mock.Mock()
        query.filter.return_value = query
        query.first.return_value = user
        database = mock.Mock()
        database.query.return_value = query
        return database

    def encode_token(self, user, *, include_password_version=True):
        payload = {"sub": user.id}
        if include_password_version:
            payload["pwdv"] = self.auth_identity.password_token_version(user.password_hash)
        return self.auth.jwt.encode(payload, self.secret, algorithm=self.auth_identity.JWT_ALGORITHM)

    def test_login_token_is_bound_to_current_password_hash(self):
        user = self.user()
        database = self.database_for(user)
        request = self.schemas.LoginRequest(
            email=user.email,
            password="CurrentPassword1!",
        )

        with mock.patch.object(self.auth, "verify_password", return_value=True):
            result = self.auth.login(request, database)

        payload = self.auth.jwt.decode(
            result.token,
            self.secret,
            algorithms=[self.auth_identity.JWT_ALGORITHM],
        )
        self.assertEqual(
            self.auth_identity.password_token_version(user.password_hash),
            payload.get("pwdv"),
        )

    def test_password_bound_token_succeeds_and_old_or_unbound_tokens_fail(self):
        user = self.user()
        database = self.database_for(user)
        valid = SimpleNamespace(credentials=self.encode_token(user))

        self.assertIs(user, self.auth_identity.get_current_user(valid, database))

        missing_version = SimpleNamespace(
            credentials=self.encode_token(user, include_password_version=False)
        )
        with self.assertRaises(HTTPException) as raised:
            self.auth_identity.get_current_user(missing_version, database)
        self.assertEqual(401, raised.exception.status_code)

        old_token = valid
        user.password_hash = "hash:ChangedPassword2!"
        with self.assertRaises(HTTPException) as raised:
            self.auth_identity.get_current_user(old_token, database)
        self.assertEqual(401, raised.exception.status_code)

    def test_wrong_current_password_does_not_update_or_commit(self):
        user = self.user()
        database = mock.Mock()
        payload = self.schemas.ChangePasswordRequest(
            current_password="WrongPassword1!",
            new_password="ChangedPassword2!",
            new_password2="ChangedPassword2!",
        )

        with mock.patch.object(self.auth, "verify_password", return_value=False):
            with self.assertRaises(HTTPException) as raised:
                self.auth.change_password(payload, user, database)

        self.assertEqual(400, raised.exception.status_code)
        self.assertEqual("hash:CurrentPassword1!", user.password_hash)
        database.commit.assert_not_called()
        database.rollback.assert_not_called()

    def test_change_password_updates_only_authenticated_user(self):
        user = self.user()
        other = self.user(password_hash="hash:OtherPassword1!")
        other.id = 8
        database = mock.Mock()
        payload = self.schemas.ChangePasswordRequest(
            current_password="CurrentPassword1!",
            new_password="ChangedPassword2!",
            new_password2="ChangedPassword2!",
        )

        with mock.patch.object(self.auth, "verify_password", return_value=True), mock.patch.object(
            self.auth,
            "hash_password",
            return_value="hash:ChangedPassword2!",
        ):
            result = self.auth.change_password(payload, user, database)

        self.assertEqual({"ok": True}, result)
        self.assertEqual("hash:ChangedPassword2!", user.password_hash)
        self.assertEqual("hash:OtherPassword1!", other.password_hash)
        database.query.assert_not_called()
        database.commit.assert_called_once_with()
        database.rollback.assert_not_called()

    def test_password_confirmation_policy_and_unchanged_value_are_enforced(self):
        invalid_payloads = (
            {
                "current_password": "CurrentPassword1!",
                "new_password": "ChangedPassword2!",
                "new_password2": "DifferentPassword3!",
            },
            {
                "current_password": "CurrentPassword1!",
                "new_password": "CurrentPassword1!",
                "new_password2": "CurrentPassword1!",
            },
            {
                "current_password": "CurrentPassword1!",
                "new_password": "short",
                "new_password2": "short",
            },
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    self.schemas.ChangePasswordRequest(**payload)

    def test_database_failure_rolls_back_without_leaking_details(self):
        user = self.user()
        database = mock.Mock()
        database.commit.side_effect = SQLAlchemyError("private database detail")
        payload = self.schemas.ChangePasswordRequest(
            current_password="CurrentPassword1!",
            new_password="ChangedPassword2!",
            new_password2="ChangedPassword2!",
        )

        with mock.patch.object(self.auth, "verify_password", return_value=True), mock.patch.object(
            self.auth,
            "hash_password",
            return_value="hash:ChangedPassword2!",
        ):
            with self.assertRaises(HTTPException) as raised:
                self.auth.change_password(payload, user, database)

        self.assertEqual(500, raised.exception.status_code)
        self.assertNotIn("private database detail", str(raised.exception.detail))
        database.rollback.assert_called_once_with()

    def test_change_password_route_is_competition_only(self):
        competition_paths = {route.path for route in self.auth.competition_router.routes}
        legacy_paths = {route.path for route in self.auth.router.routes}
        self.assertIn("/auth/change-password", competition_paths)
        self.assertNotIn("/auth/change-password", legacy_paths)


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
