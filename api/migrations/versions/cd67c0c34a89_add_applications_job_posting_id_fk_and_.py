"""add applications job_posting_id fk and index

applications.job_posting_id was added in 011 as a plain integer with no
foreign key, although the Application model declares ForeignKey and index.
Add both so the database refuses to delete a job_postings row that an
application still references.

Revision ID: cd67c0c34a89
Revises: a4001bda2f32
Create Date: 2026-10-28 09:57:58.989983

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'cd67c0c34a89'
down_revision: str | None = 'a4001bda2f32'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Never fix dangling references silently — they are user data. Stop with a
    # clear message so they can be reviewed first.
    dangling = op.get_bind().execute(sa.text("""
        SELECT COUNT(*) FROM applications a
        WHERE a.job_posting_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM job_postings jp WHERE jp.id = a.job_posting_id)
    """)).scalar()
    if dangling:
        raise RuntimeError(
            f"{dangling} applications row(s) reference a missing job_postings row; "
            "resolve them before adding applications_job_posting_id_fkey"
        )

    op.create_foreign_key(
        'applications_job_posting_id_fkey',
        'applications',
        'job_postings',
        ['job_posting_id'],
        ['id'],
    )
    op.create_index('ix_applications_job_posting_id', 'applications', ['job_posting_id'])


def downgrade() -> None:
    op.drop_index('ix_applications_job_posting_id', table_name='applications')
    op.drop_constraint('applications_job_posting_id_fkey', 'applications', type_='foreignkey')
