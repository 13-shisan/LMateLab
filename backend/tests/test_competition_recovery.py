import json
from unittest import mock

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models_workflow import WorkflowAttempt, WorkflowEvent, WorkflowFile, WorkflowRun, WorkflowStep
from tests.test_competition_coordinator import CoordinatorTestCase


class CompetitionRecoveryTests(CoordinatorTestCase):
    def test_fresh_coordinator_reconciles_running_job_without_duplicate_submission(self):
        self.start()
        attempt = self.latest_attempt("relax")
        self.slurm.set_state(
            attempt.id,
            "running",
            raw_state="RUNNING",
            exit_code="0:0",
        )
        submissions_before = list(self.slurm.submitted_steps)

        first = self.new_coordinator().tick_once()
        second = self.new_coordinator().tick_once()

        self.assertEqual((1, 0), (first.processed, first.failures))
        self.assertEqual((1, 0), (second.processed, second.failures))
        self.assertEqual(submissions_before, self.slurm.submitted_steps)
        self.assertEqual("running", self.latest_attempt("relax").status)
        self.assertEqual(1, self.attempt_count("relax"))

    def test_scheduler_outage_preserves_last_trusted_state_until_fresh_recovery(self):
        self.start()
        attempt = self.latest_attempt("relax")
        self.slurm.set_state(
            attempt.id,
            "running",
            raw_state="RUNNING",
            exit_code="0:0",
        )
        self.new_coordinator().tick_once()
        self.assertEqual("running", self.latest_attempt("relax").status)

        self.slurm.set_state(
            attempt.id,
            "unknown",
            raw_state=None,
            exit_code=None,
            stale=True,
            error_code="scheduler_record_unavailable",
        )
        outage = self.new_coordinator().tick_once()
        stale_attempt = self.latest_attempt("relax")
        stale_metadata = json.loads(stale_attempt.metadata_json)["scheduler_observation"]

        self.assertEqual((1, 0), (outage.processed, outage.failures))
        self.assertEqual("running", stale_attempt.status)
        self.assertTrue(stale_metadata["stale"])
        self.assertIsNotNone(stale_metadata["stale_since"])
        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual(0, self.attempt_count("scf"))

        stale_since = stale_metadata["stale_since"]
        self.new_coordinator().tick_once()
        repeated = json.loads(
            self.latest_attempt("relax").metadata_json
        )["scheduler_observation"]
        self.assertEqual(stale_since, repeated["stale_since"])

        self.slurm.set_state(
            attempt.id,
            "running",
            raw_state="RUNNING",
            exit_code="0:0",
            stale=False,
            error_code=None,
        )
        recovered = self.new_coordinator().tick_once()
        trusted = json.loads(
            self.latest_attempt("relax").metadata_json
        )["scheduler_observation"]
        self.assertEqual((1, 0), (recovered.processed, recovered.failures))
        self.assertEqual("running", self.latest_attempt("relax").status)
        self.assertFalse(trusted["stale"])
        self.assertNotIn("stale_since", trusted)

    def test_acceptance_database_failure_never_submits_the_next_stage(self):
        self.start()
        relax = self.latest_attempt("relax")
        self.slurm.set_state(
            relax.id,
            "succeeded",
            raw_state="COMPLETED",
            exit_code="0:0",
        )
        original_commit = Session.commit
        commit_calls = 0

        def fail_acceptance_commit(session):
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 2:
                raise RuntimeError("database unavailable")
            return original_commit(session)

        with mock.patch.object(Session, "commit", fail_acceptance_commit):
            tick = self.new_coordinator().tick_once()

        self.assertEqual((1, 1), (tick.processed, tick.failures))
        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual(0, self.attempt_count("scf"))
        self.assertEqual("awaiting_acceptance", self.latest_attempt("relax").status)
        with self.SessionLocal() as session:
            self.assertEqual(
                0,
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowFile)
                    .where(WorkflowFile.attempt_id == relax.id)
                ),
            )
            self.assertEqual(
                0,
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowEvent)
                    .where(
                        WorkflowEvent.workflow_id == self.workflow_id,
                        WorkflowEvent.event_type == "scientific_acceptance_completed",
                    )
                ),
            )

    def test_committed_cancel_intent_wins_over_completed_scheduler_state(self):
        self.start()
        relax = self.latest_attempt("relax")
        self.slurm.set_state(
            relax.id,
            "succeeded",
            raw_state="COMPLETED",
            exit_code="0:0",
        )
        with self.SessionLocal() as session:
            outcome = self.reconciler.reconcile_attempt(session, relax.id)
            self.assertEqual("awaiting_acceptance", outcome.status)
            attempt = session.get(WorkflowAttempt, relax.id)
            metadata = json.loads(attempt.metadata_json)
            metadata["cancel_result"] = {
                "result": "requested",
                "observed_at": metadata["scheduler_observation"]["observed_at"],
            }
            attempt.metadata_json = metadata
            session.commit()

        self.new_coordinator().tick_once()

        with self.SessionLocal() as session:
            attempt = session.get(WorkflowAttempt, relax.id)
            step = session.get(WorkflowStep, attempt.step_id)
            run = session.get(WorkflowRun, self.workflow_id)
            self.assertEqual(
                ("cancelled", "cancelled", "cancelled"),
                (attempt.status, step.status, run.status),
            )
        self.assertEqual([], self.acceptance.calls)
        self.assertEqual(["relax"], self.slurm.submitted_steps)
        self.assertEqual(0, self.attempt_count("scf"))


if __name__ == "__main__":
    import unittest

    unittest.main()
