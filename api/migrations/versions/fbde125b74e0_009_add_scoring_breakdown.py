"""009 add scoring_breakdown to job_postings

Revision ID: fbde125b74e0
Revises: 276095669f8d
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'fbde125b74e0'
down_revision = '276095669f8d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('job_postings', sa.Column('scoring_breakdown', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('job_postings', 'scoring_breakdown')
