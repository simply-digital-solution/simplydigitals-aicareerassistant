"""006_add_job_postings

Revision ID: a1b2c3d4e5f6
Revises: 6fb74988967f
Create Date: 2026-06-14 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '6fb74988967f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'job_postings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('mcf_uuid', sa.String(100), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('company', sa.String(255), nullable=False),
        sa.Column('url', sa.String(1000), nullable=False),
        sa.Column('location', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('inferred_industries', sa.Text(), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scraped_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('scored', sa.Boolean(), nullable=False, default=False),
        sa.Column('fit_score', sa.Float(), nullable=True),
        sa.Column('reasons', sa.Text(), nullable=True),
        sa.Column('risks', sa.Text(), nullable=True),
        sa.Column('key_keywords', sa.Text(), nullable=True),
        sa.Column('scored_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'mcf_uuid', name='uq_job_postings_user_uuid'),
    )
    op.create_index('ix_job_postings_user_id', 'job_postings', ['user_id'])
    op.create_index('ix_job_postings_scored', 'job_postings', ['scored'])


def downgrade() -> None:
    op.drop_index('ix_job_postings_scored', table_name='job_postings')
    op.drop_index('ix_job_postings_user_id', table_name='job_postings')
    op.drop_table('job_postings')
