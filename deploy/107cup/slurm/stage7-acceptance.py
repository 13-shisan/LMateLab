from __future__ import annotations

import argparse
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from competition_runtime import release_commit, workflow_root
from database import SessionLocal
from main_107cup import build_production_coordinator
from models import User
from schemas_workflow import DraftCreateRequest
from services.competition_inputs import FIXED_STEPS
from services.competition_workflows import (
    confirm_workflow,
    create_internal_acceptance_draft,
)


_ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _operator_id(session: Session, alias: str) -> int:
    if _ALIAS_RE.fullmatch(alias) is None:
        raise RuntimeError("operator alias is invalid")
    operators = list(
        session.scalars(
            select(User)
            .where(User.alias == alias, User.role == "operator")
            .limit(2)
        )
    )
    if len(operators) != 1:
        raise RuntimeError("operator identity is unavailable")
    return int(operators[0].id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("scf_nonconvergence_v1",), required=True)
    parser.add_argument("--operator-alias", default="pb23030683")
    args = parser.parse_args()

    root = workflow_root()
    payload = DraftCreateRequest.model_validate(
        {
            "template_version": "mos2_v1",
            "source_kind": "builtin",
            "steps": list(FIXED_STEPS),
            "parameters": {},
        }
    )
    with SessionLocal() as session:
        owner_id = _operator_id(session, args.operator_alias)
        draft = create_internal_acceptance_draft(
            session,
            root,
            owner_id=owner_id,
            payload=payload,
            release_commit=release_commit(),
            profile=args.profile,
        )
        confirm_workflow(
            session,
            root,
            owner_id=owner_id,
            workflow_id=draft.id,
        )

    coordinator = build_production_coordinator()
    outcome = coordinator.start(draft.id, owner_id)
    print(outcome.workflow_id, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
