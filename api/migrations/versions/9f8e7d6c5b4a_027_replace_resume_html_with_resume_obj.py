"""027 replace resume_html with resume_obj

Revision ID: 9f8e7d6c5b4a
Revises: 4ec03e16864f
Create Date: 2026-06-23

"""
from alembic import op
import sqlalchemy as sa

revision = '9f8e7d6c5b4a'
down_revision = '4ec03e16864f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('resume_obj', sa.Text(), nullable=True))
    op.drop_column('profiles', 'resume_html')


def downgrade() -> None:
    op.add_column('profiles', sa.Column('resume_html', sa.Text(), nullable=True))
    op.drop_column('profiles', 'resume_obj')
