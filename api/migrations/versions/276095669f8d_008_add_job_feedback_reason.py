"""008_add_job_feedback_reason

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
    op.add_column('job_feedback', sa.Column('reason', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('job_feedback', 'reason')
