"""031 replace scored+rescoring booleans with scoring_status enum

Revision ID: d5e6f7a8b9c1
Revises: c4d5e6f7a8b0
Create Date: 2026-07-02
"""
from typing import Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd5e6f7a8b9c1'
down_revision: Union[str, None] = 'c4d5e6f7a8b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_job_postings',
        sa.Column('scoring_status', sa.String(20), nullable=False, server_default='idle'),
    )

    # Backfill from existing boolean columns — order matters:
    #   rescoring=true → these are stale locks; reset to idle
    #   scored=true     → completed
    #   scored=false, score_error IS NOT NULL → failed
    #   scored=false, score_error IS NULL     → idle (already the default)
    op.execute("""
        UPDATE user_job_postings SET scoring_status = 'idle'
        WHERE rescoring = true
    """)
    op.execute("""
        UPDATE user_job_postings SET scoring_status = 'completed'
        WHERE scored = true AND rescoring = false
    """)
    op.execute("""
        UPDATE user_job_postings SET scoring_status = 'failed'
        WHERE scored = false AND rescoring = false AND score_error IS NOT NULL
    """)

    op.drop_column('user_job_postings', 'scored')
    op.drop_column('user_job_postings', 'rescoring')


def downgrade() -> None:
    op.add_column(
        'user_job_postings',
        sa.Column('scored', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column(
        'user_job_postings',
        sa.Column('rescoring', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.execute("""
        UPDATE user_job_postings SET scored = true
        WHERE scoring_status = 'completed'
    """)
    op.execute("""
        UPDATE user_job_postings SET rescoring = true
        WHERE scoring_status = 'in_progress'
    """)
    op.drop_column('user_job_postings', 'scoring_status')
