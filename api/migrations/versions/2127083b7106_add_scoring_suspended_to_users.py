"""add scoring_suspended to users

Revision ID: 2127083b7106
Revises: a1b2c3d4e5f7
Create Date: 2026-06-18 19:08:15.786063

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2127083b7106'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('scoring_suspended', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('users', 'scoring_suspended')
