"""014 add google oauth to profiles

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4a5b6c7d8e9'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('google_access_token', sa.Text(), nullable=True))
    op.add_column('profiles', sa.Column('google_refresh_token', sa.Text(), nullable=True))
    op.add_column('profiles', sa.Column('google_token_expiry', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'google_token_expiry')
    op.drop_column('profiles', 'google_refresh_token')
    op.drop_column('profiles', 'google_access_token')
