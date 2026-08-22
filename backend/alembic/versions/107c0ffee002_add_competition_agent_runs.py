"""add competition Agent runs

Revision ID: 107c0ffee002
Revises: 107c0ffee001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "107c0ffee002"
down_revision: Union[str, Sequence[str], None] = "107c0ffee001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "competition_agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=True),
        sa.Column("request_kind", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_competition_agent_runs_owner_id", "competition_agent_runs", ["owner_id"])
    op.create_index("ix_competition_agent_runs_status", "competition_agent_runs", ["status"])
    op.create_index("ix_competition_agent_runs_approved_at", "competition_agent_runs", ["approved_at"])


def downgrade() -> None:
    op.drop_index("ix_competition_agent_runs_approved_at", table_name="competition_agent_runs")
    op.drop_index("ix_competition_agent_runs_status", table_name="competition_agent_runs")
    op.drop_index("ix_competition_agent_runs_owner_id", table_name="competition_agent_runs")
    op.drop_table("competition_agent_runs")
