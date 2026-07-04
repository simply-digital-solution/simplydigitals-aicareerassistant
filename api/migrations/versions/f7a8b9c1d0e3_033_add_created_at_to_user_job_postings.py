"""033 add created_at to user_job_postings

Revision ID: f7a8b9c1d0e3
Revises: e6f7a8b9c0d2
Create Date: 2026-07-04

Adds created_at to user_job_postings so it can be used as a stable
insertion-order tiebreaker when sorting research jobs.
The column exists in the SQLAlchemy model but had no migration.

Backfilled using id ordering (ascending id = earlier insertion).
"""
from typing import Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f7a8b9c1d0e3'
down_revision: Union[str, None] = 'e6f7a8b9c0d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_job_postings',
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Backfill: assign a synthetic timestamp based on row insertion order.
    # All rows get the same base time offset by their rank within their user,
    # so the relative order is preserved even though exact time is approximate.
    op.execute("""
        UPDATE user_job_postings ujp
        SET created_at = NOW() - INTERVAL '1 second' * (
            SELECT COUNT(*)
            FROM user_job_postings ujp2
            WHERE ujp2.id > ujp.id
        )
    """)


def downgrade() -> None:
    op.drop_column('user_job_postings', 'created_at')
