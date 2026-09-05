"""add materialized personal VASP records

Revision ID: 107c0ffee003
Revises: 107c0ffee002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "107c0ffee003"
down_revision: Union[str, Sequence[str], None] = "107c0ffee002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "personal_vasp_records",
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("artifact_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("formula", sa.String(length=100), nullable=False),
        sa.Column("elements_json", sa.Text(), nullable=False),
        sa.Column("energy", sa.Float(), nullable=True),
        sa.Column("bandgap_eV", sa.Float(), nullable=True),
        sa.Column("vbm_eV", sa.Float(), nullable=True),
        sa.Column("cbm_eV", sa.Float(), nullable=True),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workflow_id"),
    )
    op.create_index("ix_personal_vasp_records_owner_id", "personal_vasp_records", ["owner_id"])
    op.create_index("ix_personal_vasp_records_formula", "personal_vasp_records", ["formula"])
    op.create_index("ix_personal_vasp_records_bandgap", "personal_vasp_records", ["bandgap_eV"])


def downgrade() -> None:
    op.drop_index("ix_personal_vasp_records_bandgap", table_name="personal_vasp_records")
    op.drop_index("ix_personal_vasp_records_formula", table_name="personal_vasp_records")
    op.drop_index("ix_personal_vasp_records_owner_id", table_name="personal_vasp_records")
    op.drop_table("personal_vasp_records")
