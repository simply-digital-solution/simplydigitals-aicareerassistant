"""002_add_session_id_result_json_drafts_user

Revision ID: e25e116630a8
Revises: 3ae16ef93275
Create Date: 2026-05-02 15:27:51.302325

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e25e116630a8'
down_revision: Union[str, None] = '3ae16ef93275'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agent_jobs', sa.Column('session_id', sa.String(length=100), nullable=True))
    op.add_column('agent_jobs', sa.Column('result_json', sa.Text(), nullable=True))
    # SQLite does not support ALTER COLUMN — skip the NOT NULL change on agent_name
    op.create_index(op.f('ix_agent_jobs_session_id'), 'agent_jobs', ['session_id'], unique=False)
    op.add_column('drafts', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('drafts', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_drafts_user_id'), 'drafts', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_drafts_user_id'), table_name='drafts')
    op.drop_column('drafts', 'reviewed_at')
    op.drop_column('drafts', 'user_id')
    op.drop_index(op.f('ix_agent_jobs_session_id'), table_name='agent_jobs')
    op.drop_column('agent_jobs', 'result_json')
    op.drop_column('agent_jobs', 'session_id')
