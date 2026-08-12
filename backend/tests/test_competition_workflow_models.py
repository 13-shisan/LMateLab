import json
import math
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from database import Base
from models import User
from models_workflow import (
    WorkflowAttempt,
    WorkflowEvent,
    WorkflowFile,
    WorkflowRun,
    WorkflowStep,
    WorkflowTemplate,
    canonical_json,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
CURRENT_HEAD = "2f694f47e108"
WORKFLOW_HEAD = "107c0ffee001"
WORKFLOW_TABLES = {
    "workflow_runs",
    "workflow_steps",
    "workflow_attempts",
    "workflow_events",
    "workflow_files",
    "workflow_templates",
}


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def _upgrade(path: Path, revision: str) -> None:
    config = Config(str(ALEMBIC_INI))
    database_url = _database_url(path)
    config.set_main_option("sqlalchemy.url", database_url)
    with patch.dict(os.environ, {"DATABASE_URL": database_url}):
        command.upgrade(config, revision)


def _sqlite_engine(path: Path):
    engine = create_engine(_database_url(path))

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


class CompetitionWorkflowMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def database_path(self, name: str) -> Path:
        return Path(self.temp_dir.name) / name

    def test_revision_is_the_only_head_and_env_registers_workflow_models(self):
        config = Config(str(ALEMBIC_INI))
        script = ScriptDirectory.from_config(config)

        self.assertEqual(script.get_heads(), [WORKFLOW_HEAD])
        self.assertEqual(script.get_revision(WORKFLOW_HEAD).down_revision, CURRENT_HEAD)
        self.assertIn(
            "import models_workflow",
            (BACKEND_ROOT / "alembic" / "env.py").read_text(encoding="utf-8"),
        )
        self.assertTrue(WORKFLOW_TABLES.issubset(Base.metadata.tables))

    def test_fresh_database_upgrades_to_empty_workflow_schema(self):
        database_path = self.database_path("fresh.sqlite")
        _upgrade(database_path, "head")

        engine = _sqlite_engine(database_path)
        self.addCleanup(engine.dispose)
        inspector = inspect(engine)

        self.assertTrue(WORKFLOW_TABLES.issubset(inspector.get_table_names()))
        with engine.connect() as connection:
            for table_name in WORKFLOW_TABLES:
                count = connection.scalar(text(f"SELECT COUNT(*) FROM {table_name}"))
                self.assertEqual(count, 0, f"migration seeded {table_name}")

    def test_database_at_current_head_upgrades_with_constraints_and_cascade(self):
        database_path = self.database_path("upgrade.sqlite")
        _upgrade(database_path, CURRENT_HEAD)

        before_engine = _sqlite_engine(database_path)
        self.assertTrue(WORKFLOW_TABLES.isdisjoint(inspect(before_engine).get_table_names()))
        before_engine.dispose()

        _upgrade(database_path, "head")
        engine = _sqlite_engine(database_path)
        self.addCleanup(engine.dispose)
        inspector = inspect(engine)

        expected_unique_constraints = {
            "workflow_templates": {("template_key", "version")},
            "workflow_steps": {("workflow_id", "step_key")},
            "workflow_attempts": {("step_id", "attempt_number")},
            "workflow_events": {("workflow_id", "sequence")},
            "workflow_files": {("workflow_id", "relative_path")},
        }
        for table_name, expected in expected_unique_constraints.items():
            actual = {
                tuple(constraint["column_names"])
                for constraint in inspector.get_unique_constraints(table_name)
            }
            self.assertTrue(expected.issubset(actual), table_name)

        expected_foreign_keys = {
            ("workflow_runs", "owner_id", "users", "id", ""),
            ("workflow_steps", "workflow_id", "workflow_runs", "id", "CASCADE"),
            ("workflow_attempts", "step_id", "workflow_steps", "id", "CASCADE"),
            ("workflow_events", "workflow_id", "workflow_runs", "id", "CASCADE"),
            ("workflow_files", "workflow_id", "workflow_runs", "id", "CASCADE"),
            ("workflow_files", "attempt_id", "workflow_attempts", "id", "CASCADE"),
            ("workflow_files", "owner_id", "users", "id", ""),
        }
        actual_foreign_keys = set()
        for table_name in WORKFLOW_TABLES:
            for foreign_key in inspector.get_foreign_keys(table_name):
                actual_foreign_keys.add(
                    (
                        table_name,
                        foreign_key["constrained_columns"][0],
                        foreign_key["referred_table"],
                        foreign_key["referred_columns"][0],
                        foreign_key.get("options", {}).get("ondelete", "").upper(),
                    )
                )
        self.assertEqual(expected_foreign_keys, actual_foreign_keys)

        self._assert_run_delete_cascades(engine)

    def _assert_run_delete_cascades(self, engine) -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email, password_hash, name, alias, role, created_at) "
                    "VALUES (1, 'owner@example.com', 'hash', 'owner', '', 'user', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO workflow_runs "
                    "(id, owner_id, template_version, material, source_kind, status, "
                    "metadata_json, created_at, updated_at) "
                    "VALUES ('run-1', 1, 'mos2_v1', 'MoS2', 'builtin', 'draft', "
                    "'{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO workflow_steps "
                    "(id, workflow_id, step_key, position, status, parameters_json, "
                    "created_at, updated_at) "
                    "VALUES (1, 'run-1', 'relax', 0, 'waiting', '{}', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO workflow_attempts "
                    "(id, step_id, attempt_number, status, metadata_json, created_at, updated_at) "
                    "VALUES ('attempt-1', 1, 1, 'created', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO workflow_events "
                    "(id, workflow_id, sequence, event_type, payload_json, created_at) "
                    "VALUES (1, 'run-1', 1, 'draft_created', '{}', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO workflow_files "
                    "(id, workflow_id, attempt_id, owner_id, relative_path, size_bytes, "
                    "sha256, source_kind, metadata_json, created_at) "
                    "VALUES ('file-1', 'run-1', 'attempt-1', 1, 'attempts/1/OUTCAR', 1, "
                    "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
                    "'generated', '{}', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(text("DELETE FROM workflow_runs WHERE id = 'run-1'"))

            for table_name in (
                "workflow_steps",
                "workflow_attempts",
                "workflow_events",
                "workflow_files",
            ):
                self.assertEqual(
                    connection.scalar(text(f"SELECT COUNT(*) FROM {table_name}")),
                    0,
                    table_name,
                )


class CompetitionWorkflowModelTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "models.sqlite"
        _upgrade(self.database_path, "head")
        self.engine = _sqlite_engine(self.database_path)
        self.addCleanup(self.engine.dispose)

    def test_uuid_utc_and_canonical_json_defaults(self):
        payload = {"z": [2, 1], "label": "\u4e8c\u786b\u5316\u94bc", "a": {"enabled": True}}
        encoded = canonical_json(payload)
        self.assertEqual(
            encoded,
            '{"a":{"enabled":true},"label":"\u4e8c\u786b\u5316\u94bc","z":[2,1]}',
        )
        self.assertEqual(json.loads(encoded), payload)
        for non_finite in (math.nan, math.inf, -math.inf):
            with self.subTest(non_finite=non_finite):
                with self.assertRaises(ValueError):
                    canonical_json({"value": non_finite})

        with Session(self.engine, expire_on_commit=False) as session:
            owner = User(
                email="workflow-owner@example.com",
                password_hash="hash",
                name="workflow-owner",
                alias="",
                role="user",
                created_at=datetime.now(timezone.utc),
            )
            run = WorkflowRun(
                owner=owner,
                template_version="mos2_v1",
                material="MoS2",
                source_kind="builtin",
                metadata_json=encoded,
            )
            step = WorkflowStep(
                workflow=run,
                step_key="relax",
                position=0,
                parameters_json=canonical_json({"encut": 500}),
            )
            incoming_file = WorkflowFile(
                owner=owner,
                relative_path="incoming/source",
                size_bytes=10,
                sha256="a" * 64,
                source_kind="upload",
                metadata_json=canonical_json({"filename": "POSCAR"}),
            )
            session.add_all([run, step, incoming_file])
            session.flush()

            self.assertEqual(
                session.scalar(select(func.count()).select_from(WorkflowAttempt)),
                0,
            )
            for generated_id in (run.id, incoming_file.id):
                self.assertEqual(str(uuid.UUID(generated_id)), generated_id)
            for timestamp in (run.created_at, run.updated_at, step.created_at, incoming_file.created_at):
                self.assertIsNotNone(timestamp.tzinfo)
                self.assertEqual(timestamp.utcoffset(), timezone.utc.utcoffset(timestamp))

            attempt = WorkflowAttempt(
                step=step,
                attempt_number=1,
                metadata_json=canonical_json({}),
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
            event_row = WorkflowEvent(
                workflow=run,
                sequence=1,
                event_type="draft_created",
                payload_json=canonical_json({"source": "builtin"}),
            )
            template = WorkflowTemplate(
                template_key="mos2",
                version="mos2_v1",
                definition_json=canonical_json({"steps": ["relax", "scf", "band", "dos"]}),
            )
            session.add_all([attempt, event_row, template])
            session.flush()

            self.assertEqual(str(uuid.UUID(attempt.id)), attempt.id)
            self.assertIsNotNone(attempt.created_at.tzinfo)
            self.assertIsNotNone(event_row.created_at.tzinfo)
            self.assertIsNotNone(template.created_at.tzinfo)

            persisted_ids = {
                WorkflowRun: run.id,
                WorkflowStep: step.id,
                WorkflowAttempt: attempt.id,
                WorkflowEvent: event_row.id,
                WorkflowFile: incoming_file.id,
                WorkflowTemplate: template.id,
            }
            session.commit()

        with Session(self.engine) as session:
            persisted_timestamps = []
            for model, record_id in persisted_ids.items():
                record = session.get(model, record_id)
                self.assertIsNotNone(record)
                persisted_timestamps.extend(
                    getattr(record, attribute)
                    for attribute in (
                        "created_at",
                        "updated_at",
                        "started_at",
                        "finished_at",
                    )
                    if hasattr(record, attribute) and getattr(record, attribute) is not None
                )

            for timestamp in persisted_timestamps:
                self.assertIsNotNone(timestamp.tzinfo)
                self.assertEqual(timestamp.utcoffset(), timezone.utc.utcoffset(timestamp))

    def test_utc_timestamps_remain_aware_after_sqlite_round_trip(self):
        with Session(self.engine) as session:
            owner = User(
                email="round-trip-owner@example.com",
                password_hash="hash",
                name="round-trip-owner",
                alias="",
                role="user",
                created_at=datetime.now(timezone.utc),
            )
            run = WorkflowRun(
                owner=owner,
                template_version="mos2_v1",
                material="MoS2",
                source_kind="builtin",
            )
            session.add(run)
            session.commit()
            run_id = run.id

        with Session(self.engine) as session:
            persisted = session.get(WorkflowRun, run_id)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.created_at.tzinfo, timezone.utc)
            self.assertEqual(persisted.updated_at.tzinfo, timezone.utc)

    def test_json_columns_canonicalize_objects_sequences_and_json_text(self):
        with Session(self.engine) as session:
            owner = User(
                email="json-owner@example.com",
                password_hash="hash",
                name="json-owner",
                alias="",
                role="user",
                created_at=datetime.now(timezone.utc),
            )
            run = WorkflowRun(
                owner=owner,
                template_version="mos2_v1",
                material="MoS2",
                source_kind="builtin",
                metadata_json=' { "z" : 2, "a" : 1 } ',
            )
            step = WorkflowStep(
                workflow=run,
                step_key="relax",
                position=0,
                parameters_json={"sigma": 0.05, "encut": 500},
            )
            attempt = WorkflowAttempt(
                step=step,
                attempt_number=1,
                metadata_json={"resources": {"gpu": 1}},
            )
            event_row = WorkflowEvent(
                workflow=run,
                sequence=1,
                event_type="draft_created",
                payload_json=[{"z": 2, "a": 1}],
            )
            file_row = WorkflowFile(
                workflow=run,
                attempt=attempt,
                owner=owner,
                relative_path="attempts/1/OUTCAR",
                size_bytes=1,
                sha256="b" * 64,
                source_kind="generated",
                metadata_json=' { "kind" : "output" } ',
            )
            template = WorkflowTemplate(
                template_key="mos2",
                version="mos2_v1",
                definition_json={"steps": ["relax", "scf", "band", "dos"]},
            )
            session.add_all([run, step, attempt, event_row, file_row, template])
            session.commit()

            expected = {
                ("workflow_runs", "metadata_json", run.id): '{"a":1,"z":2}',
                ("workflow_steps", "parameters_json", step.id): '{"encut":500,"sigma":0.05}',
                ("workflow_attempts", "metadata_json", attempt.id): '{"resources":{"gpu":1}}',
                ("workflow_events", "payload_json", event_row.id): '[{"a":1,"z":2}]',
                ("workflow_files", "metadata_json", file_row.id): '{"kind":"output"}',
                ("workflow_templates", "definition_json", template.id): (
                    '{"steps":["relax","scf","band","dos"]}'
                ),
            }

        with self.engine.connect() as connection:
            for (table_name, column_name, record_id), encoded in expected.items():
                with self.subTest(table=table_name):
                    actual = connection.scalar(
                        text(
                            f"SELECT {column_name} FROM {table_name} "
                            "WHERE id = :record_id"
                        ),
                        {"record_id": record_id},
                    )
                    self.assertEqual(actual, encoded)

    def test_json_columns_reject_invalid_and_non_finite_values(self):
        with Session(self.engine) as session:
            owner = User(
                email="invalid-json-owner@example.com",
                password_hash="hash",
                name="invalid-json-owner",
                alias="",
                role="user",
                created_at=datetime.now(timezone.utc),
            )
            session.add(owner)
            session.commit()
            owner_id = owner.id

        invalid_values = (
            "not-json",
            '{"value":NaN}',
            '{"value":Infinity}',
            {"value": math.nan},
            [math.inf],
        )
        for value in invalid_values:
            with self.subTest(value=value), Session(self.engine) as session:
                session.add(
                    WorkflowRun(
                        owner_id=owner_id,
                        template_version="mos2_v1",
                        material="MoS2",
                        source_kind="builtin",
                        metadata_json=value,
                    )
                )
                with self.assertRaises(StatementError):
                    session.flush()


if __name__ == "__main__":
    unittest.main()
