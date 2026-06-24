"""
Job posting cleanup and archival.

Two daily operations:

1. archive_old_job_postings (runs first, 04:00 SGT)
   Sets user_job_postings.archived = true for any unactioned job whose
   posted_at is older than ARCHIVE_POSTING_DAYS (14 days).  Keeps the
   scoring queue small — stale postings are almost certainly filled, so
   sending them to the LLM wastes tokens.  Jobs linked to any application
   are never auto-archived.

2. purge_stale_research_jobs (runs second, 04:00 SGT)
   Physically deletes job_postings rows that have been archived for long
   enough (STALE_JOB_DAYS = 30).  Keeps the table lean.
   Protected if referenced by generated_resumes.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from app.shared.sql_compat import now_utc

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ARCHIVE_POSTING_DAYS = 14   # auto-archive jobs older than this
STALE_JOB_DAYS = 30         # physically delete rows older than this

# Statuses that indicate the user has acted on the job — these rows must NEVER be auto-archived or deleted.
_PROTECTED_STATUSES = ("applied", "interviewing", "offered", "rejected", "withdrawn", "archived")


async def archive_old_job_postings(
    db: AsyncSession,
    days: int = ARCHIVE_POSTING_DAYS,
) -> int:
    """
    Set archived=true on user_job_postings rows whose job was posted more than
    `days` days ago, provided no application exists for that job+user pair.

    Jobs with NULL posted_at are skipped (Postgres NULL < date is false).
    Returns the number of rows archived.
    """
    cutoff = now_utc() - timedelta(days=days)

    result = await db.execute(text("""
        UPDATE user_job_postings
        SET archived = true
        WHERE archived = false
          AND job_posting_id IN (
              SELECT id FROM job_postings
              WHERE posted_at < :cutoff
          )
          AND NOT EXISTS (
              SELECT 1 FROM applications a
              WHERE a.job_posting_id = user_job_postings.job_posting_id
                AND a.user_id = user_job_postings.user_id
          )
    """), {"cutoff": cutoff})
    await db.commit()

    archived = result.rowcount
    logger.info("job_cleanup: archived %d user_job_postings row(s) with posted_at older than %d days", archived, days)
    return archived


async def purge_stale_research_jobs(
    db: AsyncSession,
    days: int = STALE_JOB_DAYS,
) -> int:
    """
    Delete stale job_postings and return the number of rows removed.

    A job is deleted when ALL of the following hold:
      1. scraped_at is older than `days` days ago
      2. No application referencing this job has an actioned status
         (applied / interviewing / offered / rejected / withdrawn / archived)
      3. No generated_resume references this job (the resume document is still live)
    """
    cutoff = now_utc() - timedelta(days=days)
    statuses = ",".join(f"'{s}'" for s in _PROTECTED_STATUSES)

    # Find IDs to delete in a single query to avoid a slow correlated subquery inside DELETE.
    candidate_rows = await db.execute(text(f"""
        SELECT jp.id
        FROM job_postings jp
        WHERE jp.scraped_at < :cutoff
          AND jp.id NOT IN (
              SELECT a.job_posting_id
              FROM applications a
              WHERE a.job_posting_id IS NOT NULL
                AND a.status IN ({statuses})
          )
          AND jp.id NOT IN (
              SELECT gr.job_posting_id
              FROM generated_resumes gr
              WHERE gr.job_posting_id IS NOT NULL
          )
    """), {"cutoff": cutoff})

    ids = [row[0] for row in candidate_rows.fetchall()]
    if not ids:
        logger.info("job_cleanup: no stale research jobs to delete")
        return 0

    placeholders = ",".join(str(i) for i in ids)
    # Delete user_job_postings first — it has a FK to job_postings.id with no CASCADE.
    await db.execute(text(f"DELETE FROM user_job_postings WHERE job_posting_id IN ({placeholders})"))
    await db.execute(text(f"DELETE FROM job_postings WHERE id IN ({placeholders})"))
    await db.commit()

    logger.info("job_cleanup: deleted %d stale research job(s) older than %d days", len(ids), days)
    return len(ids)
