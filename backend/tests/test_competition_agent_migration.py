import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class CompetitionAgentMigrationTests(unittest.TestCase):
    def test_upgrade_adds_empty_agent_table_without_touching_workflow_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "agent-migration.sqlite"
            database_url = f"sqlite:///{database_path.resolve().as_posix()}"
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            config.set_main_option("sqlalchemy.url", database_url)
            with patch.dict(os.environ, {"DATABASE_URL": database_url}):
                command.upgrade(config, "107c0ffee001")
            engine = create_engine(database_url)
            with engine.begin() as connection:
                before = connection.scalar(text("SELECT COUNT(*) FROM workflow_runs"))
            engine.dispose()

            with patch.dict(os.environ, {"DATABASE_URL": database_url}):
                command.upgrade(config, "head")
            engine = create_engine(database_url)
            try:
                self.assertIn("competition_agent_runs", inspect(engine).get_table_names())
                with engine.connect() as connection:
                    self.assertEqual(before, connection.scalar(text("SELECT COUNT(*) FROM workflow_runs")))
                    self.assertEqual(0, connection.scalar(text("SELECT COUNT(*) FROM competition_agent_runs")))
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
