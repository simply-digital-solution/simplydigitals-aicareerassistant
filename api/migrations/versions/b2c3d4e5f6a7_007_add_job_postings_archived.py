"""007_add_job_postings_archived

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-14 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'job_postings',
        sa.Column('archived', sa.Boolean(), nullable=False, server_default='0'),
    )
    op.create_index('ix_job_postings_archived', 'job_postings', ['archived'])


def downgrade() -> None:
    op.drop_index('ix_job_postings_archived', table_name='job_postings')
    op.drop_column('job_postings', 'archived')
