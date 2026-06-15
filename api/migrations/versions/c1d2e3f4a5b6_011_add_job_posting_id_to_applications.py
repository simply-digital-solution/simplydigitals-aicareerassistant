"""011 add job_posting_id to applications

Revision ID: c1d2e3f4a5b6
Revises: 8053b6a19c50
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = '8053b6a19c50'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('job_posting_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('applications', 'job_posting_id')
