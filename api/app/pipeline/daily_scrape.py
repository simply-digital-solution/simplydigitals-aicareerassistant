"""
Daily scraper — pulls MCF jobs for every user based on their profile.

Deduplication rules:
  job_postings: unique by mcf_uuid — content is shared across users.
  user_job_postings: unique by (user_id, job_posting_id) — per-user scoring row.
  Same job re-posted on a different date is kept (may have updated requirements).
"""
import json
import logging
import time
from datetime import datetime, timezone
from app.shared.sql_compat import now_utc

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.pipeline.scraper import scrape_mycareersfuture
from app.shared.models import Profile
from app.modules.agents.router import _filter_by_industry

logger = logging.getLogger(__name__)


async def scrape_for_user(user_id: int, db: AsyncSession) -> int:
    """
    Scrape MCF for a single user's target titles and insert new job rows.
    Returns the number of new rows inserted.
    """
    t_user_start = time.monotonic()

    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        logger.warning("scrape_for_user: no profile for user_id=%d", user_id)
        return 0

    target_titles: list[str] = json.loads(profile.target_titles) if profile.target_titles else []
    target_industries: list[str] = json.loads(profile.target_industries) if profile.target_industries else []

    if not target_titles:
        logger.info("scrape_for_user: user_id=%d has no target titles, skipping", user_id)
        return 0

    logger.info(
        "scrape_for_user: user_id=%d starting — titles=%s industries=%s",
        user_id, target_titles, target_industries or ["(no filter)"],
    )

    inserted = 0
    now = now_utc()

    for title in target_titles:
        t_title_start = time.monotonic()
        logger.info("scrape_for_user: user_id=%d fetching MCF for title=%r", user_id, title)
        try:
            jobs = await scrape_mycareersfuture(query=title, max_results=100)
        except Exception as exc:
            logger.warning("scrape_for_user: user_id=%d MCF fetch failed for title=%r: %s", user_id, title, exc)
            continue

        fetched = len(jobs)
        logger.info(
            "scrape_for_user: user_id=%d title=%r MCF returned %d jobs in %.2fs",
            user_id, title, fetched, time.monotonic() - t_title_start,
        )

        # Apply industry filter before inserting
        if target_industries:
            jobs = _filter_by_industry(jobs, target_industries, threshold=0.80)
            logger.info(
                "scrape_for_user: user_id=%d title=%r after industry filter: %d/%d jobs kept",
                user_id, title, len(jobs), fetched,
            )

        title_inserted = 0
        title_skipped = 0
        for job in jobs:
            uuid = job.get("url", "").rstrip("/").split("/")[-1]
            if not uuid:
                title_skipped += 1
                continue

            posted_at = None
            posted_str = job.get("posted_at") or job.get("scraped_at")
            if posted_str:
                try:
                    parsed = datetime.fromisoformat(posted_str.replace("Z", "+00:00"))
                    # fromisoformat returns date when string is "YYYY-MM-DD" — promote to datetime
                    if not hasattr(parsed, 'hour'):
                        from datetime import date as _date
                        posted_at = datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)
                    else:
                        posted_at = parsed
                except (ValueError, AttributeError):
                    pass

            job_title   = job.get("title", "")
            job_company = job.get("company", "")
            posted_date = posted_at.date().isoformat() if posted_at else None

            industries_json = json.dumps(job.get("inferred_industries") or [])

            # Step 1: upsert into job_postings (content, shared across users)
            jp_row = await db.execute(
                text("""
                    INSERT INTO job_postings
                        (mcf_uuid, title, company, url, location,
                         description, inferred_industries, posted_at, scraped_at)
                    VALUES
                        (:uuid, :title, :company, :url, :location,
                         :description, :industries, :posted_at, :scraped_at)
                    ON CONFLICT (mcf_uuid) DO UPDATE SET
                        inferred_industries = CASE
                            WHEN job_postings.inferred_industries IS NULL
                              OR job_postings.inferred_industries = '[]'
                            THEN excluded.inferred_industries
                            ELSE job_postings.inferred_industries
                        END,
                        scraped_at          = excluded.scraped_at
                    RETURNING id
                """),
                {
                    "uuid":        uuid,
                    "title":       job_title,
                    "company":     job_company,
                    "url":         job.get("url", ""),
                    "location":    job.get("location", ""),
                    "description": job.get("description", ""),
                    "industries":  industries_json,
                    "posted_at":   posted_at if posted_at else None,
                    "scraped_at":  now,
                },
            )
            jp_id_row = jp_row.fetchone()
            if not jp_id_row:
                title_skipped += 1
                continue
            job_posting_id = jp_id_row[0]

            # Step 2: create user_job_postings row (unscored) if not yet exists
            ujp_row = await db.execute(
                text("""
                    INSERT INTO user_job_postings (user_id, job_posting_id, scored)
                    VALUES (:uid, :jid, false)
                    ON CONFLICT (user_id, job_posting_id) DO NOTHING
                    RETURNING id
                """),
                {"uid": user_id, "jid": job_posting_id},
            )
            if ujp_row.fetchone():
                title_inserted += 1
            else:
                title_skipped += 1

        inserted += title_inserted
        logger.info(
            "scrape_for_user: user_id=%d title=%r → inserted=%d skipped=%d",
            user_id, title, title_inserted, title_skipped,
        )

    await db.commit()
    elapsed = time.monotonic() - t_user_start
    logger.info(
        "scrape_for_user: user_id=%d done — total inserted=%d across %d titles in %.2fs",
        user_id, inserted, len(target_titles), elapsed,
    )
    return inserted


async def scrape_for_all_users(get_db_context) -> None:
    """Called by the scheduler — scrapes for every user who has a profile.

    Each user gets its own DB session so a failure for one user does not
    abort the transaction and block all subsequent users.
    """
    t_start = time.monotonic()

    async with get_db_context() as db:
        rows = await db.execute(text("""
            SELECT p.user_id FROM profiles p
            JOIN users u ON u.id = p.user_id
            WHERE u.scoring_suspended = false
        """))
        user_ids = [r[0] for r in rows.fetchall()]

    logger.info("scrape_for_all_users: starting — found %d users: %s", len(user_ids), user_ids)

    summary: dict[int, int] = {}
    for uid in user_ids:
        try:
            async with get_db_context() as db:
                summary[uid] = await scrape_for_user(uid, db)
        except Exception as exc:
            logger.error(
                "scrape_for_all_users: user_id=%d failed: %s",
                uid, exc, exc_info=True,
            )
            summary[uid] = -1

    elapsed = time.monotonic() - t_start
    logger.info(
        "scrape_for_all_users: done in %.2fs — per-user new jobs: %s",
        elapsed,
        {f"user_{uid}": count for uid, count in summary.items()},
    )
