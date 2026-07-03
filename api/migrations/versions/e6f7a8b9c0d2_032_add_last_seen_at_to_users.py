"""032 add last_seen_at to users

Revision ID: e6f7a8b9c0d2
Revises: d5e6f7a8b9c1
Create Date: 2026-07-03

Adds last_seen_at to the users table, updated on every authenticated
frontend request via get_current_user(). Replaces the misleading
MAX(agent_runs.started_at) used for last_active in the admin UI, which
was firing on background scorer calls rather than real user activity.

Backfilled from MAX(agent_runs.started_at) as a best-effort seed;
values become accurate from the first request after this migration runs.
"""
from typing import Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e6f7a8b9c0d2'
down_revision: Union[str, None] = 'd5e6f7a8b9c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("""
        UPDATE users u
        SET last_seen_at = (
            SELECT MAX(ar.started_at)
            FROM agent_runs ar
            WHERE ar.user_id = u.id
        )
    """)


def downgrade() -> None:
    op.drop_column('users', 'last_seen_at')
