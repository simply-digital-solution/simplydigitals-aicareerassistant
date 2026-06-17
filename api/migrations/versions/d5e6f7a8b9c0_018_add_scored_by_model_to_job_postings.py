"""018 add scored_by_model to job_postings

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('job_postings', sa.Column('scored_by_model', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('job_postings', 'scored_by_model')
