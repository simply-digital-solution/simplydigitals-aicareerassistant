"""022_add_seniority_target_titles_to_profiles

Revision ID: c0d1e2f3a4b5
Revises: bbe84fc91bcb
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c0d1e2f3a4b5'
down_revision: Union[str, None] = 'bbe84fc91bcb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('seniority_level', sa.String(50), nullable=True))
    op.add_column('profiles', sa.Column('target_titles', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'target_titles')
    op.drop_column('profiles', 'seniority_level')
