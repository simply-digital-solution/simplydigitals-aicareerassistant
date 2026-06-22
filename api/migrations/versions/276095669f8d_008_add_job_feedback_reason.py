"""008_create_job_feedback

Revision ID: 276095669f8d
Revises: b2c3d4e5f6a7
Create Date: 2026-06-15 09:32:13.476268

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '276095669f8d'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'job_feedback',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('job_url', sa.String(1000), nullable=False),
        sa.Column('job_title', sa.String(255), nullable=False),
        sa.Column('company', sa.String(255), nullable=False),
        sa.Column('relevance', sa.String(20), nullable=False),
        sa.Column('reason', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'job_url', name='uq_job_feedback_user_url'),
    )


def downgrade() -> None:
    op.drop_table('job_feedback')
