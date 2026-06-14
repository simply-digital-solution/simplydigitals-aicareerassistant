"""
Daily scraper — pulls MCF jobs for every user based on their profile.

Designed to be called by the scheduler at 07:00 SGT and via the on-demand
POST /research/scrape endpoint. Inserts only new job UUIDs (INSERT OR IGNORE).
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.pipeline.scraper import scrape_mycareersfuture
from app.shared.models import Profile, JobPosting
from app.modules.agents.router import _filter_by_industry

logger = logging.getLogger(__name__)


async def scrape_for_user(user_id: int, db: AsyncSession) -> int:
    """
    Scrape MCF for a single user's target titles and insert new job rows.
    Returns the number of new rows inserted.
    """
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

    inserted = 0
    now = datetime.now(timezone.utc)

    for title in target_titles:
        logger.info("scrape_for_user: user_id=%d scraping MCF for %r", user_id, title)
        try:
            jobs = await scrape_mycareersfuture(query=title, max_results=100)
        except Exception as exc:
            logger.warning("scrape_for_user: MCF failed for %r: %s", title, exc)
            continue

        # Apply industry filter before inserting
        if target_industries:
            jobs = _filter_by_industry(jobs, target_industries, threshold=0.80)

        for job in jobs:
            uuid = job.get("url", "").rstrip("/").split("/")[-1]
            if not uuid:
                continue

            posted_at = None
            posted_str = job.get("posted_at") or job.get("scraped_at")
            if posted_str:
                try:
                    posted_at = datetime.fromisoformat(posted_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            row = await db.execute(
                text("""
                    INSERT OR IGNORE INTO job_postings
                        (user_id, mcf_uuid, title, company, url, location,
                         description, inferred_industries, posted_at, scraped_at, scored)
                    VALUES
                        (:user_id, :uuid, :title, :company, :url, :location,
                         :description, :industries, :posted_at, :scraped_at, 0)
                """),
                {
                    "user_id": user_id,
                    "uuid": uuid,
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "url": job.get("url", ""),
                    "location": job.get("location", ""),
                    "description": job.get("description", ""),
                    "industries": json.dumps(job.get("inferred_industries") or []),
                    "posted_at": posted_at.isoformat() if posted_at else None,
                    "scraped_at": now.isoformat(),
                },
            )
            inserted += row.rowcount

    await db.commit()
    logger.info("scrape_for_user: user_id=%d inserted %d new jobs", user_id, inserted)
    return inserted


async def scrape_for_all_users(db: AsyncSession) -> None:
    """Called by the scheduler — scrapes for every user who has a profile."""
    rows = await db.execute(text("SELECT user_id FROM profiles"))
    user_ids = [r[0] for r in rows.fetchall()]
    logger.info("scrape_for_all_users: found %d users", len(user_ids))
    for uid in user_ids:
        try:
            await scrape_for_user(uid, db)
        except Exception as exc:
            logger.error("scrape_for_all_users: user_id=%d failed: %s", uid, exc)
