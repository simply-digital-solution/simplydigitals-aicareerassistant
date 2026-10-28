"""add drafts user_id fk

drafts.user_id was added without a foreign key, although the Draft model
declares ForeignKey("users.id"). Add it so the database refuses to delete a
user that a draft still references.

Revision ID: c4786b3256a2
Revises: cd67c0c34a89
Create Date: 2026-10-28 10:01:33.231392

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c4786b3256a2'
down_revision: str | None = 'cd67c0c34a89'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Never fix dangling references silently — they are user data. Stop with a
    # clear message so they can be reviewed first.
    dangling = op.get_bind().execute(sa.text("""
        SELECT COUNT(*) FROM drafts d
        WHERE d.user_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id = d.user_id)
    """)).scalar()
    if dangling:
        raise RuntimeError(
            f"{dangling} drafts row(s) reference a missing users row; "
            "resolve them before adding drafts_user_id_fkey"
        )

    op.create_foreign_key(
        'drafts_user_id_fkey',
        'drafts',
        'users',
        ['user_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('drafts_user_id_fkey', 'drafts', type_='foreignkey')
