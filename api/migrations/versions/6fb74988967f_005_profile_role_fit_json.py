"""005_profile_role_fit_json

Revision ID: 6fb74988967f
Revises: f86d9bcfacd3
Create Date: 2026-05-03 18:34:54.885701

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6fb74988967f'
down_revision: Union[str, None] = 'f86d9bcfacd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('role_fit_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'role_fit_json')
