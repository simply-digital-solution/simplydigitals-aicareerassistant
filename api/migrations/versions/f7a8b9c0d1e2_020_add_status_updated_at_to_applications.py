"""020 add status_updated_at to applications

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'f7a8b9c0d1e2'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(
            sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True)
        )
    # Backfill existing rows: use created_at as the baseline
    op.execute("UPDATE applications SET status_updated_at = created_at WHERE status_updated_at IS NULL")


def downgrade():
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("status_updated_at")
