"""phase 13 prompt flags and model registry

Revision ID: 20260719_phase13
Revises: 20260719_phase12
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_phase13"
down_revision = "20260719_phase12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pr_id", sa.String(length=255), nullable=False),
        sa.Column("agent", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=255), nullable=False),
        sa.Column("prompt_version", sa.String(length=255), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("variant", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_runs_pr_id", "model_runs", ["pr_id"])
    op.create_index("ix_model_runs_agent", "model_runs", ["agent"])


def downgrade() -> None:
    op.drop_index("ix_model_runs_agent", table_name="model_runs")
    op.drop_index("ix_model_runs_pr_id", table_name="model_runs")
    op.drop_table("model_runs")
