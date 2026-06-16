"""015 add drive fields to generated resumes

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'a5b6c7d8e9f0'
down_revision = 'f4a5b6c7d8e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('generated_resumes', sa.Column('drive_file_id', sa.Text(), nullable=True))
    op.add_column('generated_resumes', sa.Column('drive_link', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('generated_resumes', 'drive_link')
    op.drop_column('generated_resumes', 'drive_file_id')
