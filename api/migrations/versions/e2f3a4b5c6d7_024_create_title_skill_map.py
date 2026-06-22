"""024_create_title_skill_map

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'title_skill_map',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('required_skills', sa.Text(), nullable=False),
        sa.Column('source_keywords', sa.Text(), nullable=True),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'title', name='uq_title_skill_map_user_title'),
    )


def downgrade() -> None:
    op.drop_table('title_skill_map')
