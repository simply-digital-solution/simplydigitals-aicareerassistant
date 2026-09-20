"""add source to job_postings

Revision ID: d0474324c38b
Revises: 158e6828458d
Create Date: 2026-09-20 11:55:12.116798

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd0474324c38b'
down_revision: Union[str, None] = '158e6828458d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('job_postings', sa.Column('source', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('job_postings', 'source')
