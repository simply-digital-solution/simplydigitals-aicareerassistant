"""029_fix_generated_resumes_fk

generated_resumes.job_posting_id was still FK'd to job_postings_legacy
after the 028 split. Re-point it to the new job_postings table.

Revision ID: b3c4d5e6f7a9
Revises: a2b3c4d5e6f7
Create Date: 2026-06-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b3c4d5e6f7a9'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        'generated_resumes_job_posting_id_fkey',
        'generated_resumes',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'generated_resumes_job_posting_id_fkey',
        'generated_resumes',
        'job_postings',
        ['job_posting_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'generated_resumes_job_posting_id_fkey',
        'generated_resumes',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'generated_resumes_job_posting_id_fkey',
        'generated_resumes',
        'job_postings_legacy',
        ['job_posting_id'],
        ['id'],
    )
