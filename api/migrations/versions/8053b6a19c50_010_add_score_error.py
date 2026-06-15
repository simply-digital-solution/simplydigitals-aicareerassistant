"""010 add score_error to job_postings

Revision ID: 8053b6a19c50
Revises: fbde125b74e0
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = '8053b6a19c50'
down_revision = 'fbde125b74e0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('job_postings', sa.Column('score_error', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('job_postings', 'score_error')
