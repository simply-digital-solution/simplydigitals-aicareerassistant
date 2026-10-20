"""add additional_skills to profiles

Revision ID: 4974831d4bc4
Revises: a4001bda2f32
Create Date: 2026-10-20 09:30:09.840835

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4974831d4bc4'
down_revision: Union[str, None] = 'a4001bda2f32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('additional_skills', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'additional_skills')
