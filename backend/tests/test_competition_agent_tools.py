import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from database import Base
from models import User
from models_workflow import WorkflowRun, WorkflowStep
from services.competition_agent.tools import (
    AgentToolError,
    prepared_structure_workspace,
    sanitized_workflow_summary,
)


class CompetitionAgentToolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        db_path = Path(self.temp_dir.name) / "tools.sqlite"
        self.engine = create_engine(f"sqlite:///{db_path}")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        with Session(self.engine) as session:
            owner = User(email="owner@example.com", password_hash="x", name="Owner", alias="owner", role="operator")
            other = User(email="other@example.com", password_hash="x", name="Other", alias="other", role="operator")
            session.add_all([owner, other])
            session.flush()
            run = WorkflowRun(
                id="00000000-0000-4000-8000-000000000001",
                owner_id=owner.id,
                template_version="mos2_v1",
                material="MoS2",
                source_kind="builtin",
                status="succeeded",
                metadata_json={"private_path": "/home/private/run", "scientific_status": "accepted"},
            )
            run.steps.append(WorkflowStep(step_key="relax", position=0, status="succeeded", parameters_json={"ENCUT": 520}))
            session.add(run)
            session.commit()
            self.owner_id = owner.id
            self.other_id = other.id
            self.workflow_id = run.id

    def test_summary_is_owned_and_sanitized(self):
        with Session(self.engine) as session:
            summary = sanitized_workflow_summary(session, self.workflow_id, self.owner_id)
        self.assertEqual("MoS2", summary["material"])
        self.assertEqual([{"key": "relax", "status": "succeeded"}], summary["steps"])
        rendered = repr(summary).lower()
        for forbidden in ["/home/", "private_path", "parameters", "potcar", "job_id"]:
            self.assertNotIn(forbidden, rendered)

    def test_other_operator_workflow_is_unavailable(self):
        with Session(self.engine) as session:
            with self.assertRaisesRegex(AgentToolError, "workflow is unavailable"):
                sanitized_workflow_summary(session, self.workflow_id, self.other_id)

    def test_prepared_structure_workspace_contains_reviewable_files_without_paths_or_potcar(self):
        workspace = prepared_structure_workspace("MoS2_monolayer")

        self.assertEqual("MoS2_monolayer", workspace["material_id"])
        self.assertIn("POSCAR", workspace["files"])
        self.assertIn("KPOINTS", workspace["files"])
        self.assertNotIn("POTCAR", workspace["files"])
        rendered = repr(workspace).lower()
        self.assertNotIn("/home/", rendered)
        self.assertNotIn("absolute_path", rendered)


if __name__ == "__main__":
    unittest.main()
