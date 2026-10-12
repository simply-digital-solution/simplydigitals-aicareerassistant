"""make agent_runs user_id nullable

Revision ID: a4001bda2f32
Revises: 802cae45901c
Create Date: 2026-10-12 21:40:49.087094

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4001bda2f32'
down_revision: Union[str, None] = '802cae45901c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('agent_runs', 'user_id', nullable=True)


def downgrade() -> None:
    op.alter_column('agent_runs', 'user_id', nullable=False)
