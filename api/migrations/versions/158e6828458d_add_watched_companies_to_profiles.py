"""add watched_companies to profiles

Revision ID: 158e6828458d
Revises: f7a8b9c1d0e3
Create Date: 2026-09-02 09:11:07.201438

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '158e6828458d'
down_revision: Union[str, None] = 'f7a8b9c1d0e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('watched_companies', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'watched_companies')
