"""023_widen_job_feedback_reason

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3a4b5c6'
down_revision = 'c0d1e2f3a4b5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('job_feedback', 'reason',
                    existing_type=sa.String(100),
                    type_=sa.Text(),
                    existing_nullable=True)


def downgrade() -> None:
    op.alter_column('job_feedback', 'reason',
                    existing_type=sa.Text(),
                    type_=sa.String(100),
                    existing_nullable=True)
