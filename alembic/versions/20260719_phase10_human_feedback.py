"""phase 10 human feedback

Revision ID: 20260719_phase10
Revises: 940db59e627c
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_phase10"
down_revision = "940db59e627c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "human_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pr_id", sa.String(length=255), nullable=False),
        sa.Column("review_id", sa.String(length=255), nullable=False),
        sa.Column("finding_key", sa.String(length=255), nullable=True),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("original_message", sa.Text(), nullable=True),
        sa.Column("override_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_human_feedback_pr_id", "human_feedback", ["pr_id"])
    op.create_index("ix_human_feedback_review_id", "human_feedback", ["review_id"])


def downgrade() -> None:
    op.drop_index("ix_human_feedback_review_id", table_name="human_feedback")
    op.drop_index("ix_human_feedback_pr_id", table_name="human_feedback")
    op.drop_table("human_feedback")
