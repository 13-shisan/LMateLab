import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator

from database import Base


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _reject_non_finite_json(constant: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {constant}")


class CanonicalJSONText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            value = json.loads(value, parse_constant=_reject_non_finite_json)
        return canonical_json(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        decoded = json.loads(value, parse_constant=_reject_non_finite_json)
        return canonical_json(decoded)


def _uuid_string() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _empty_json() -> str:
    return canonical_json({})


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UTC timestamps must include timezone information")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    id = Column(Integer, primary_key=True)
    template_key = Column(String(100), nullable=False)
    version = Column(String(100), nullable=False)
    definition_json = Column(CanonicalJSONText(), nullable=False, default=_empty_json)
    created_at = Column(UTCDateTime(), nullable=False, default=_utc_now)
    updated_at = Column(
        UTCDateTime(),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    __table_args__ = (
        UniqueConstraint(
            "template_key",
            "version",
            name="uq_workflow_templates_key_version",
        ),
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(String(36), primary_key=True, default=_uuid_string)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    template_version = Column(String(100), nullable=False)
    material = Column(String(100), nullable=False)
    source_kind = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="draft")
    input_sha256 = Column(String(64), nullable=True)
    release_commit = Column(String(64), nullable=True)
    metadata_json = Column(CanonicalJSONText(), nullable=False, default=_empty_json)
    created_at = Column(UTCDateTime(), nullable=False, default=_utc_now)
    updated_at = Column(
        UTCDateTime(),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    owner = relationship("User")
    steps = relationship(
        "WorkflowStep",
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events = relationship(
        "WorkflowEvent",
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    files = relationship(
        "WorkflowFile",
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_workflow_runs_owner_id", "owner_id"),
        Index("ix_workflow_runs_status", "status"),
        Index("ix_workflow_runs_updated_at", "updated_at"),
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"

    id = Column(Integer, primary_key=True)
    workflow_id = Column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_key = Column(String(50), nullable=False)
    position = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default="waiting")
    parameters_json = Column(CanonicalJSONText(), nullable=False, default=_empty_json)
    created_at = Column(UTCDateTime(), nullable=False, default=_utc_now)
    updated_at = Column(
        UTCDateTime(),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    workflow = relationship("WorkflowRun", back_populates="steps")
    attempts = relationship(
        "WorkflowAttempt",
        back_populates="step",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "step_key",
            name="uq_workflow_steps_workflow_step",
        ),
        Index("ix_workflow_steps_workflow_id", "workflow_id"),
        Index("ix_workflow_steps_status", "status"),
    )


class WorkflowAttempt(Base):
    __tablename__ = "workflow_attempts"

    id = Column(String(36), primary_key=True, default=_uuid_string)
    step_id = Column(
        Integer,
        ForeignKey("workflow_steps.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default="created")
    slurm_job_id = Column(String(100), nullable=True)
    working_directory = Column(Text, nullable=True)
    metadata_json = Column(CanonicalJSONText(), nullable=False, default=_empty_json)
    started_at = Column(UTCDateTime(), nullable=True)
    finished_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), nullable=False, default=_utc_now)
    updated_at = Column(
        UTCDateTime(),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )

    step = relationship("WorkflowStep", back_populates="attempts")
    files = relationship(
        "WorkflowFile",
        back_populates="attempt",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "step_id",
            "attempt_number",
            name="uq_workflow_attempts_step_number",
        ),
        Index("ix_workflow_attempts_step_id", "step_id"),
        Index("ix_workflow_attempts_status", "status"),
        Index("ix_workflow_attempts_slurm_job_id", "slurm_job_id"),
    )


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id = Column(Integer, primary_key=True)
    workflow_id = Column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(100), nullable=False)
    payload_json = Column(CanonicalJSONText(), nullable=False, default=_empty_json)
    created_at = Column(UTCDateTime(), nullable=False, default=_utc_now)

    workflow = relationship("WorkflowRun", back_populates="events")

    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "sequence",
            name="uq_workflow_events_workflow_sequence",
        ),
        Index("ix_workflow_events_workflow_id", "workflow_id"),
        Index("ix_workflow_events_event_type", "event_type"),
    )


class WorkflowFile(Base):
    __tablename__ = "workflow_files"

    id = Column(String(36), primary_key=True, default=_uuid_string)
    workflow_id = Column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=True,
    )
    attempt_id = Column(
        String(36),
        ForeignKey("workflow_attempts.id", ondelete="CASCADE"),
        nullable=True,
    )
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    relative_path = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    source_kind = Column(String(50), nullable=False)
    metadata_json = Column(CanonicalJSONText(), nullable=False, default=_empty_json)
    created_at = Column(UTCDateTime(), nullable=False, default=_utc_now)

    workflow = relationship("WorkflowRun", back_populates="files")
    attempt = relationship("WorkflowAttempt", back_populates="files")
    owner = relationship("User")

    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "relative_path",
            name="uq_workflow_files_workflow_path",
        ),
        Index("ix_workflow_files_workflow_id", "workflow_id"),
        Index("ix_workflow_files_attempt_id", "attempt_id"),
        Index("ix_workflow_files_owner_id", "owner_id"),
        Index("ix_workflow_files_sha256", "sha256"),
    )
