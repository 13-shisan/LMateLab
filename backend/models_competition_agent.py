from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text

from database import Base
from models_workflow import CanonicalJSONText, UTCDateTime


def _uuid_string() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentRun(Base):
    __tablename__ = "competition_agent_runs"

    id = Column(String(36), primary_key=True, default=_uuid_string)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    workflow_id = Column(String(36), ForeignKey("workflow_runs.id"), nullable=True)
    request_kind = Column(String(50), nullable=False)
    provider = Column(String(30), nullable=False, default="mock")
    status = Column(String(30), nullable=False, default="queued")
    prompt_text = Column(Text, nullable=False)
    input_json = Column(CanonicalJSONText(), nullable=False)
    output_json = Column(CanonicalJSONText(), nullable=True)
    error_code = Column(String(100), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), nullable=False, default=_utc_now)
    updated_at = Column(UTCDateTime(), nullable=False, default=_utc_now, onupdate=_utc_now)

    __table_args__ = (
        Index("ix_competition_agent_runs_owner_id", "owner_id"),
        Index("ix_competition_agent_runs_status", "status"),
        Index("ix_competition_agent_runs_approved_at", "approved_at"),
    )
