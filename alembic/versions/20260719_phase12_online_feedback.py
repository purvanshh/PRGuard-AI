"""phase 12 online feedback loop

Revision ID: 20260719_phase12
Revises: 20260719_phase10
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260719_phase12"
down_revision = "20260719_phase10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "findings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("finding_key", sa.String(length=255), nullable=False),
        sa.Column("pr_id", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("posted_comment_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finding_key"),
    )
    op.create_index("ix_findings_finding_key", "findings", ["finding_key"])
    op.create_index("ix_findings_pr_id", "findings", ["pr_id"])
    op.create_index("ix_findings_posted_comment_id", "findings", ["posted_comment_id"])
    op.create_table(
        "online_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("finding_key", sa.String(length=255), nullable=False),
        sa.Column("pr_id", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("signal", sa.String(length=50), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_online_feedback_finding_key", "online_feedback", ["finding_key"])
    op.create_index("ix_online_feedback_pr_id", "online_feedback", ["pr_id"])
    op.create_table(
        "ab_test_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("experiment", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("variant", sa.String(length=100), nullable=False),
        sa.Column("assigned_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ab_test_assignments_experiment", "ab_test_assignments", ["experiment"])
    op.create_index("ix_ab_test_assignments_subject", "ab_test_assignments", ["subject"])
    op.create_table(
        "shadow_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pr_id", sa.String(length=255), nullable=False),
        sa.Column("model_version", sa.String(length=255), nullable=False),
        sa.Column("findings_json", sa.Text(), nullable=False),
        sa.Column("posted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shadow_runs_pr_id", "shadow_runs", ["pr_id"])
    op.create_table(
        "calibration_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version", sa.String(length=255), nullable=False),
        sa.Column("slope", sa.Float(), nullable=False),
        sa.Column("intercept", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calibration_snapshots_version", "calibration_snapshots", ["version"])


def downgrade() -> None:
    op.drop_index("ix_calibration_snapshots_version", table_name="calibration_snapshots")
    op.drop_table("calibration_snapshots")
    op.drop_index("ix_shadow_runs_pr_id", table_name="shadow_runs")
    op.drop_table("shadow_runs")
    op.drop_index("ix_ab_test_assignments_subject", table_name="ab_test_assignments")
    op.drop_index("ix_ab_test_assignments_experiment", table_name="ab_test_assignments")
    op.drop_table("ab_test_assignments")
    op.drop_index("ix_online_feedback_pr_id", table_name="online_feedback")
    op.drop_index("ix_online_feedback_finding_key", table_name="online_feedback")
    op.drop_table("online_feedback")
    op.drop_index("ix_findings_posted_comment_id", table_name="findings")
    op.drop_index("ix_findings_pr_id", table_name="findings")
    op.drop_index("ix_findings_finding_key", table_name="findings")
    op.drop_table("findings")
