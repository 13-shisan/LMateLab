"""add competition workflows

Revision ID: 107c0ffee001
Revises: 2f694f47e108
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "107c0ffee001"
down_revision: Union[str, Sequence[str], None] = "2f694f47e108"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_key", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_key",
            "version",
            name="uq_workflow_templates_key_version",
        ),
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("template_version", sa.String(length=100), nullable=False),
        sa.Column("material", sa.String(length=100), nullable=False),
        sa.Column("source_kind", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=True),
        sa.Column("release_commit", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_runs_owner_id", "workflow_runs", ["owner_id"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])
    op.create_index("ix_workflow_runs_updated_at", "workflow_runs", ["updated_at"])

    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("step_key", sa.String(length=50), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_id",
            "step_key",
            name="uq_workflow_steps_workflow_step",
        ),
    )
    op.create_index("ix_workflow_steps_workflow_id", "workflow_steps", ["workflow_id"])
    op.create_index("ix_workflow_steps_status", "workflow_steps", ["status"])

    op.create_table(
        "workflow_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("slurm_job_id", sa.String(length=100), nullable=True),
        sa.Column("working_directory", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["workflow_steps.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "step_id",
            "attempt_number",
            name="uq_workflow_attempts_step_number",
        ),
    )
    op.create_index("ix_workflow_attempts_step_id", "workflow_attempts", ["step_id"])
    op.create_index("ix_workflow_attempts_status", "workflow_attempts", ["status"])
    op.create_index(
        "ix_workflow_attempts_slurm_job_id",
        "workflow_attempts",
        ["slurm_job_id"],
    )

    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_id",
            "sequence",
            name="uq_workflow_events_workflow_sequence",
        ),
    )
    op.create_index("ix_workflow_events_workflow_id", "workflow_events", ["workflow_id"])
    op.create_index("ix_workflow_events_event_type", "workflow_events", ["event_type"])

    op.create_table(
        "workflow_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=True),
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source_kind", sa.String(length=50), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["workflow_attempts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_id",
            "relative_path",
            name="uq_workflow_files_workflow_path",
        ),
    )
    op.create_index("ix_workflow_files_workflow_id", "workflow_files", ["workflow_id"])
    op.create_index("ix_workflow_files_attempt_id", "workflow_files", ["attempt_id"])
    op.create_index("ix_workflow_files_owner_id", "workflow_files", ["owner_id"])
    op.create_index("ix_workflow_files_sha256", "workflow_files", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_workflow_files_sha256", table_name="workflow_files")
    op.drop_index("ix_workflow_files_owner_id", table_name="workflow_files")
    op.drop_index("ix_workflow_files_attempt_id", table_name="workflow_files")
    op.drop_index("ix_workflow_files_workflow_id", table_name="workflow_files")
    op.drop_table("workflow_files")

    op.drop_index("ix_workflow_events_event_type", table_name="workflow_events")
    op.drop_index("ix_workflow_events_workflow_id", table_name="workflow_events")
    op.drop_table("workflow_events")

    op.drop_index("ix_workflow_attempts_slurm_job_id", table_name="workflow_attempts")
    op.drop_index("ix_workflow_attempts_status", table_name="workflow_attempts")
    op.drop_index("ix_workflow_attempts_step_id", table_name="workflow_attempts")
    op.drop_table("workflow_attempts")

    op.drop_index("ix_workflow_steps_status", table_name="workflow_steps")
    op.drop_index("ix_workflow_steps_workflow_id", table_name="workflow_steps")
    op.drop_table("workflow_steps")

    op.drop_index("ix_workflow_runs_updated_at", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_owner_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_table("workflow_templates")
