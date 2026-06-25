"""030_fix_llm_usage_logs_fk

llm_usage_logs.job_posting_id was still FK'd to job_postings_legacy
after the 028 split. Re-point it to the new job_postings table.

Revision ID: c4d5e6f7a8b0
Revises: b3c4d5e6f7a9
Create Date: 2026-06-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c4d5e6f7a8b0'
down_revision: Union[str, None] = 'b3c4d5e6f7a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        'llm_usage_logs_job_posting_id_fkey',
        'llm_usage_logs',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'llm_usage_logs_job_posting_id_fkey',
        'llm_usage_logs',
        'job_postings',
        ['job_posting_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'llm_usage_logs_job_posting_id_fkey',
        'llm_usage_logs',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'llm_usage_logs_job_posting_id_fkey',
        'llm_usage_logs',
        'job_postings_legacy',
        ['job_posting_id'],
        ['id'],
    )
