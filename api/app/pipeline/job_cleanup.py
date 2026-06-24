"""
Stale research job cleanup.

Deletes job_postings rows that are sitting in the Research tab
(never actioned past the 'selected' stage) and are older than
STALE_JOB_DAYS days.  This keeps the table lean and scoring
queries fast.

Safe-to-delete definition:
  - scraped_at < now - STALE_JOB_DAYS
  - NOT referenced by any application with status in
    (applied, interviewing, offered, rejected, withdrawn, archived)

Jobs with a 'selected' application are also deleted after the
cutoff — the user had their chance to act and didn't.
Jobs referenced by generated_resumes are protected (kept) because
the resume document is still useful to the user.

Called daily by the scheduler and exposed via admin endpoint.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from app.shared.sql_compat import now_utc

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

STALE_JOB_DAYS = 30

# Statuses that indicate the user has acted on the job — these rows must NEVER be deleted.
_PROTECTED_STATUSES = ("applied", "interviewing", "offered", "rejected", "withdrawn", "archived")


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
