from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "107cup" / "migrate-agent-history.py"
SPEC = importlib.util.spec_from_file_location("agent_history_migration", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AgentHistoryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "eln.db"
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE users (
              id INTEGER PRIMARY KEY, email TEXT NOT NULL, role TEXT NOT NULL
            );
            CREATE TABLE workflow_runs (id TEXT PRIMARY KEY);
            CREATE TABLE competition_agent_runs (
              id TEXT PRIMARY KEY,
              owner_id INTEGER NOT NULL REFERENCES users(id),
              workflow_id TEXT REFERENCES workflow_runs(id),
              request_kind TEXT NOT NULL,
              provider TEXT NOT NULL,
              status TEXT NOT NULL,
              prompt_text TEXT NOT NULL,
              input_json TEXT NOT NULL,
              output_json TEXT,
              error_code TEXT,
              approved_by_id INTEGER REFERENCES users(id),
              approved_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            INSERT INTO users (id, email, role) VALUES (7, 'jbwu@mail.ustc.edu.cn', 'operator');
            """
        )
        connection.commit()
        connection.close()
        self.database.chmod(0o600)

    def tearDown(self):
        self.temporary.cleanup()

    def export(self, **overrides):
        run_id = str(uuid.uuid4())
        conversation_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "id": run_id,
            "request_kind": "general_qa",
            "provider": "llm",
            "status": "succeeded",
            "workflow_id": None,
            "conversation_id": conversation_id,
            "prompt": "解释这次计算。",
            "input": {"conversation_id": conversation_id},
            "output": {"summary": "计算已经完成。"},
            "error_code": None,
            "approved": False,
            "created_at": now,
            "updated_at": now,
        }
        item.update(overrides)
        path = self.root / f"export-{uuid.uuid4()}.json"
        path.write_text(json.dumps({
            "format": MODULE.EXPORT_FORMAT,
            "complete": True,
            "source_user": {"email": "jbwu@mail.ustc.edu.cn"},
            "items": [item],
        }), encoding="utf-8")
        path.chmod(0o600)
        return path, item

    def migrate(self, source, *, apply):
        return MODULE.migrate(
            source_export=source,
            target_database=self.database,
            owner_email="jbwu@mail.ustc.edu.cn",
            backup_dir=self.root / "backups",
            label="12345",
            apply=apply,
        )

    def test_dry_run_does_not_write_or_backup(self):
        source, _ = self.export()
        report = self.migrate(source, apply=False)
        self.assertEqual(1, report["pending_count"])
        self.assertEqual(0, report["inserted_count"])
        self.assertFalse((self.root / "backups").exists())
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM competition_agent_runs"
            ).fetchone()[0])
        finally:
            connection.close()

    def test_apply_inserts_once_and_keeps_an_integrity_checked_backup(self):
        source, item = self.export()
        report = self.migrate(source, apply=True)
        self.assertEqual([item["id"]], report["inserted_ids"])
        backup = Path(report["backup_path"])
        self.assertTrue(backup.is_file())
        verify = sqlite3.connect(backup)
        try:
            self.assertEqual("ok", verify.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            verify.close()
        connection = sqlite3.connect(self.database)
        try:
            row = connection.execute(
                "SELECT owner_id, prompt_text, input_json, output_json FROM competition_agent_runs"
            ).fetchone()
            self.assertEqual(7, row[0])
            self.assertEqual(item["prompt"], row[1])
            self.assertEqual(item["input"], json.loads(row[2]))
            self.assertEqual(item["output"], json.loads(row[3]))
        finally:
            connection.close()

    def test_conflicting_id_aborts_without_changing_target(self):
        source, item = self.export()
        first = self.migrate(source, apply=True)
        self.assertEqual(1, first["inserted_count"])
        second_source, _ = self.export(id=item["id"], prompt="不同内容")
        with self.assertRaisesRegex(MODULE.AgentHistoryMigrationError, "conflicts"):
            self.migrate(second_source, apply=True)
        connection = sqlite3.connect(self.database)
        try:
            prompt = connection.execute(
                "SELECT prompt_text FROM competition_agent_runs WHERE id=?", (item["id"],)
            ).fetchone()[0]
            self.assertEqual(item["prompt"], prompt)
        finally:
            connection.close()

    def test_nonterminal_source_run_is_rejected(self):
        source, _ = self.export(status="running")
        with self.assertRaisesRegex(MODULE.AgentHistoryMigrationError, "not terminal"):
            self.migrate(source, apply=False)

    def test_export_without_completeness_proof_is_rejected(self):
        source, _ = self.export()
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["complete"] = False
        source.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.AgentHistoryMigrationError, "not proven complete"):
            self.migrate(source, apply=False)


if __name__ == "__main__":
    unittest.main()
