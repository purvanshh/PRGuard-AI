"""initial

Revision ID: 940db59e627c
Revises: 
Create Date: 2026-06-25 14:11:23.388718

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '940db59e627c'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'agent_logs',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('pr_id', sa.String(length=255), nullable=False),
        sa.Column('agent', sa.String(length=100), nullable=False),
        sa.Column('started_at', sa.Float(), nullable=False),
        sa.Column('finished_at', sa.Float(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('token_usage', sa.Integer(), nullable=True),
        sa.Column('execution_duration', sa.Float(), nullable=True),
        sa.Column('agent_order', sa.Integer(), nullable=True),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_logs_pr_id'), 'agent_logs', ['pr_id'], unique=False)

    op.create_table(
        'llm_usage',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('pr_id', sa.String(length=255), nullable=False),
        sa.Column('agent', sa.String(length=100), nullable=False),
        sa.Column('model', sa.String(length=255), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False),
        sa.Column('completion_tokens', sa.Integer(), nullable=False),
        sa.Column('estimated_cost_usd', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_llm_usage_pr_id'), 'llm_usage', ['pr_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_llm_usage_pr_id'), table_name='llm_usage')
    op.drop_table('llm_usage')
    op.drop_index(op.f('ix_agent_logs_pr_id'), table_name='agent_logs')
    op.drop_table('agent_logs')
