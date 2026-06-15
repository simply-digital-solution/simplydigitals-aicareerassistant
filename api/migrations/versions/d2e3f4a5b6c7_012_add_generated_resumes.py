"""012 add generated_resumes table

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'generated_resumes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('job_posting_id', sa.Integer(), sa.ForeignKey('job_postings.id'), nullable=False),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id'), nullable=True),
        sa.Column('resume_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'job_posting_id', name='uq_generated_resume_user_job'),
    )


def downgrade() -> None:
    op.drop_table('generated_resumes')
