"""add_education_certifications_phone_to_profiles

Revision ID: bbe84fc91bcb
Revises: 2127083b7106
Create Date: 2026-06-19 21:29:51.974557

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bbe84fc91bcb'
down_revision: Union[str, None] = '2127083b7106'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('education', sa.Text(), nullable=True))
    op.add_column('profiles', sa.Column('certifications', sa.Text(), nullable=True))
    op.add_column('profiles', sa.Column('phone_number', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'phone_number')
    op.drop_column('profiles', 'certifications')
    op.drop_column('profiles', 'education')
