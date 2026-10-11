"""add default to user_job_postings created_at

Revision ID: 802cae45901c
Revises: d0474324c38b
Create Date: 2026-10-11 12:44:24.683312

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '802cae45901c'
down_revision: Union[str, None] = 'd0474324c38b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill existing NULL rows using the parent job_postings.scraped_at
    # as the closest available proxy — the true original insert time was
    # never captured, so this is an approximation, not the real value.
    op.execute("""
        UPDATE user_job_postings ujp
        SET created_at = jp.scraped_at
        FROM job_postings jp
        WHERE ujp.job_posting_id = jp.id
          AND ujp.created_at IS NULL
    """)

    op.alter_column(
        'user_job_postings', 'created_at',
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.text('now()'),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'user_job_postings', 'created_at',
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
        nullable=True,
    )
