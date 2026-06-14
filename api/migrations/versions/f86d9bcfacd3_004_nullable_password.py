"""004_nullable_password

Revision ID: f86d9bcfacd3
Revises: f3a9c8d12b45
Create Date: 2026-05-03 17:57:55.537425

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f86d9bcfacd3'
down_revision: Union[str, None] = 'f3a9c8d12b45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite does not enforce NOT NULL on existing columns at the DDL level,
    # so no schema change is needed — the ORM model change (nullable=True) is sufficient.
    pass


def downgrade() -> None:
    pass
