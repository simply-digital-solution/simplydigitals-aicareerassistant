"""026 interview_packs add drive fields

Revision ID: 4ec03e16864f
Revises: f3a4b5c6d7e8
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = '4ec03e16864f'
down_revision = 'f3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('interview_packs', sa.Column('drive_file_id', sa.Text(), nullable=True))
    op.add_column('interview_packs', sa.Column('drive_link', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('interview_packs', 'drive_link')
    op.drop_column('interview_packs', 'drive_file_id')
