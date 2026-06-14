"""003 profile search preferences

Revision ID: f3a9c8d12b45
Revises: e25e116630a8
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3a9c8d12b45'
down_revision = 'e25e116630a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('remote_preference', sa.String(20), nullable=True, server_default='any'))
    op.add_column('profiles', sa.Column('employment_type', sa.String(20), nullable=True, server_default='any'))
    op.add_column('profiles', sa.Column('salary_floor', sa.Integer(), nullable=True))
    op.add_column('profiles', sa.Column('salary_currency', sa.String(10), nullable=True, server_default='USD'))
    op.add_column('profiles', sa.Column('excluded_companies', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'excluded_companies')
    op.drop_column('profiles', 'salary_currency')
    op.drop_column('profiles', 'salary_floor')
    op.drop_column('profiles', 'employment_type')
    op.drop_column('profiles', 'remote_preference')
