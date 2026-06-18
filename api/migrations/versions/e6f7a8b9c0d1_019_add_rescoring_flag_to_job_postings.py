"""019 add rescoring flag to job_postings

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('job_postings', sa.Column('rescoring', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('job_postings', 'rescoring')
