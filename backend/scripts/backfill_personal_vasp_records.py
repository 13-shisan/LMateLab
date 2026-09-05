from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from competition_runtime import workflow_root
from database import SessionLocal
from models import User  # noqa: F401 - registers relationship targets for standalone execution
from models_workflow import WorkflowRun, WorkflowStep
from services.competition_personal_results import PersonalResultIndex
from services.competition_results import CompetitionResultService


def main() -> int:
    index = PersonalResultIndex(CompetitionResultService(workflow_root=workflow_root()))
    indexed = 0
    skipped = 0
    with SessionLocal() as session:
        runs = session.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.status == "succeeded")
            .options(
                selectinload(WorkflowRun.steps).selectinload(WorkflowStep.attempts),
                selectinload(WorkflowRun.files),
                selectinload(WorkflowRun.events),
            )
            .order_by(WorkflowRun.updated_at, WorkflowRun.id)
        ).unique()
        for run in runs:
            if index.sync(session, run) is None:
                skipped += 1
            else:
                indexed += 1
        session.commit()
    print(f"personal VASP records indexed={indexed} unchanged_or_unparseable={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
