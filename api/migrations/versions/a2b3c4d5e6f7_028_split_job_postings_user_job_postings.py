"""028_split_job_postings_user_job_postings

Split the monolithic job_postings table into:
  - job_postings (content only, deduplicated by mcf_uuid)
  - user_job_postings (user-specific scoring/status, references job_postings.id)

Old table is renamed to job_postings_legacy for safety.

Revision ID: a2b3c4d5e6f7
Revises: 9f8e7d6c5b4a
Create Date: 2026-06-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = '9f8e7d6c5b4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Rename old table to legacy ─────────────────────────────────────────
    op.rename_table('job_postings', 'job_postings_legacy')

    # ── 2. Create new content-only job_postings ───────────────────────────────
    op.create_table(
        'job_postings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('mcf_uuid', sa.String(100), nullable=False, unique=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('company', sa.String(255), nullable=False),
        sa.Column('url', sa.String(1000), nullable=False),
        sa.Column('location', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('inferred_industries', sa.Text(), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scraped_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_job_postings_mcf_uuid', 'job_postings', ['mcf_uuid'], unique=True)

    # ── 3. Create user_job_postings ───────────────────────────────────────────
    op.create_table(
        'user_job_postings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('job_posting_id', sa.Integer(), sa.ForeignKey('job_postings.id'), nullable=False, index=True),
        sa.Column('scored', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('fit_score', sa.Float(), nullable=True),
        sa.Column('reasons', sa.Text(), nullable=True),
        sa.Column('risks', sa.Text(), nullable=True),
        sa.Column('key_keywords', sa.Text(), nullable=True),
        sa.Column('scoring_breakdown', sa.Text(), nullable=True),
        sa.Column('score_error', sa.Text(), nullable=True),
        sa.Column('scored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=True),
        sa.Column('rescoring', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('scored_by_model', sa.String(100), nullable=True),
        sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.UniqueConstraint('user_id', 'job_posting_id', name='uq_user_job_postings_user_job'),
    )
    op.create_index('ix_user_job_postings_scored', 'user_job_postings', ['scored'])
    op.create_index('ix_user_job_postings_archived', 'user_job_postings', ['archived'])

    # ── 4. Migrate data ───────────────────────────────────────────────────────
    # 4a. Populate new job_postings — one row per unique mcf_uuid (keep earliest scraped row)
    op.execute(sa.text("""
        INSERT INTO job_postings (mcf_uuid, title, company, url, location,
                                  description, inferred_industries, posted_at, scraped_at)
        SELECT DISTINCT ON (mcf_uuid)
               mcf_uuid, title, company, url, location,
               description, inferred_industries, posted_at, scraped_at
        FROM job_postings_legacy
        ORDER BY mcf_uuid, id ASC
    """))

    # 4b. Populate user_job_postings from legacy rows
    op.execute(sa.text("""
        INSERT INTO user_job_postings
            (user_id, job_posting_id, scored, fit_score, reasons, risks,
             key_keywords, scoring_breakdown, score_error, scored_at,
             recommendation, rescoring, scored_by_model, archived)
        SELECT
            l.user_id,
            jp.id AS job_posting_id,
            l.scored,
            l.fit_score,
            l.reasons,
            l.risks,
            l.key_keywords,
            l.scoring_breakdown,
            l.score_error,
            l.scored_at,
            l.recommendation,
            l.rescoring,
            l.scored_by_model,
            l.archived
        FROM job_postings_legacy l
        JOIN job_postings jp ON jp.mcf_uuid = l.mcf_uuid
        ON CONFLICT (user_id, job_posting_id) DO NOTHING
    """))

    # 4c. Update applications.job_posting_id to point to new job_postings.id
    op.execute(sa.text("""
        UPDATE applications a
        SET job_posting_id = jp.id
        FROM job_postings_legacy l
        JOIN job_postings jp ON jp.mcf_uuid = l.mcf_uuid
        WHERE a.job_posting_id = l.id
    """))

    # 4d. Update generated_resumes.job_posting_id to point to new job_postings.id
    op.execute(sa.text("""
        UPDATE generated_resumes gr
        SET job_posting_id = jp.id
        FROM job_postings_legacy l
        JOIN job_postings jp ON jp.mcf_uuid = l.mcf_uuid
        WHERE gr.job_posting_id = l.id
    """))

    # 4e. Update llm_usage_logs.job_posting_id to point to new job_postings.id
    op.execute(sa.text("""
        UPDATE llm_usage_logs lul
        SET job_posting_id = jp.id
        FROM job_postings_legacy l
        JOIN job_postings jp ON jp.mcf_uuid = l.mcf_uuid
        WHERE lul.job_posting_id = l.id
    """))


def downgrade() -> None:
    # Drop new tables
    op.drop_index('ix_user_job_postings_archived', table_name='user_job_postings')
    op.drop_index('ix_user_job_postings_scored', table_name='user_job_postings')
    op.drop_table('user_job_postings')
    op.drop_index('ix_job_postings_mcf_uuid', table_name='job_postings')
    op.drop_table('job_postings')
    # Restore original table
    op.rename_table('job_postings_legacy', 'job_postings')
