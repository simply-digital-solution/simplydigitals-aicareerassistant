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
from app.pipeline.ats_scrapers import detect_ats_platform, scrape_greenhouse, scrape_workday
from app.shared.models import Profile
from app.modules.agents.router import _filter_by_industry

logger = logging.getLogger(__name__)


def _parse_posted_at(job: dict) -> datetime | None:
    """Parse a scraped job dict's posted_at (falling back to scraped_at) into
    a timezone-aware datetime, or None if neither is present/parseable."""
    posted_str = job.get("posted_at") or job.get("scraped_at")
    if not posted_str:
        return None
    try:
        parsed = datetime.fromisoformat(posted_str.replace("Z", "+00:00"))
        if not hasattr(parsed, "hour"):
            return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)
        return parsed
    except (ValueError, AttributeError):
        return None


async def _insert_jobs_for_user(
    user_id: int, jobs: list[dict], db: AsyncSession, now: datetime,
) -> tuple[int, int]:
    """
    Upsert scraped job dicts into job_postings, then create idle
    user_job_postings rows for this user. Returns (inserted, skipped).

    Shared by every scraper source (MCF, Greenhouse, Workday, ...) — all
    produce the same dict shape, so this insert/dedup logic is written once.
    """
    inserted = 0
    skipped = 0

    for job in jobs:
        # Prefer an explicit external_id (set by scrapers whose URLs embed
        # the full job title, e.g. Workday) — the URL's last path segment
        # alone can exceed job_postings.mcf_uuid's varchar(100) limit.
        uuid = job.get("external_id") or job.get("url", "").rstrip("/").split("/")[-1]
        uuid = uuid[:100]
        if not uuid:
            skipped += 1
            continue

        posted_at = _parse_posted_at(job)
        industries_json = json.dumps(job.get("inferred_industries") or [])

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
                "title":       job.get("title", ""),
                "company":     job.get("company", ""),
                "url":         job.get("url", ""),
                "location":    job.get("location", ""),
                "description": job.get("description", ""),
                "industries":  industries_json,
                "posted_at":   posted_at,
                "scraped_at":  now,
            },
        )
        jp_id_row = jp_row.fetchone()
        if not jp_id_row:
            skipped += 1
            continue
        job_posting_id = jp_id_row[0]

        ujp_row = await db.execute(
            text("""
                INSERT INTO user_job_postings (user_id, job_posting_id, scoring_status)
                VALUES (:uid, :jid, 'idle')
                ON CONFLICT (user_id, job_posting_id) DO NOTHING
                RETURNING id
            """),
            {"uid": user_id, "jid": job_posting_id},
        )
        if ujp_row.fetchone():
            inserted += 1
        else:
            skipped += 1

    return inserted, skipped


async def scrape_for_user(user_id: int, db: AsyncSession, shutdown_event=None) -> int:
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
        if shutdown_event and shutdown_event.is_set():
            logger.warning(
                "scrape_for_user: user_id=%d shutdown signal — stopping before title=%r", user_id, title
            )
            break
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

        title_inserted, title_skipped = await _insert_jobs_for_user(user_id, jobs, db, now)

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


async def scrape_watchlist_for_user(user_id: int, db: AsyncSession) -> int:
    """
    Scrape each of a user's watched companies (profile.watched_companies)
    for job postings and insert new rows. Returns the number of new rows
    inserted.

    The ATS platform is detected from each entry's URL — entries on an
    unsupported platform (anything other than Greenhouse or Workday today)
    are skipped with a log message, not treated as an error, since the
    watchlist is user-curated and may include companies we can't scrape yet.
    """
    t_start = time.monotonic()

    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        logger.warning("scrape_watchlist_for_user: no profile for user_id=%d", user_id)
        return 0

    watched: list[dict] = json.loads(profile.watched_companies) if profile.watched_companies else []
    if not watched:
        logger.info("scrape_watchlist_for_user: user_id=%d has no watched companies, skipping", user_id)
        return 0

    target_titles: list[str] = json.loads(profile.target_titles) if profile.target_titles else []

    logger.info(
        "scrape_watchlist_for_user: user_id=%d starting — %d watched companies",
        user_id, len(watched),
    )

    inserted = 0
    now = now_utc()

    for company in watched:
        name = company.get("name", "")
        url = company.get("url", "")
        platform = detect_ats_platform(url)

        if platform == "greenhouse":
            try:
                jobs = await scrape_greenhouse(url, name)
            except Exception as exc:
                logger.warning(
                    "scrape_watchlist_for_user: user_id=%d Greenhouse fetch failed for %r: %s",
                    user_id, name, exc,
                )
                continue
        elif platform == "workday":
            jobs = []
            queries = target_titles or [""]
            for query in queries:
                try:
                    jobs += await scrape_workday(url, name, query=query, max_results=20)
                except Exception as exc:
                    logger.warning(
                        "scrape_watchlist_for_user: user_id=%d Workday fetch failed for %r query=%r: %s",
                        user_id, name, query, exc,
                    )
        else:
            logger.info(
                "scrape_watchlist_for_user: user_id=%d skipping %r — unsupported platform for url=%r",
                user_id, name, url,
            )
            continue

        company_inserted, company_skipped = await _insert_jobs_for_user(user_id, jobs, db, now)
        inserted += company_inserted
        logger.info(
            "scrape_watchlist_for_user: user_id=%d company=%r platform=%r → inserted=%d skipped=%d",
            user_id, name, platform, company_inserted, company_skipped,
        )

    await db.commit()
    elapsed = time.monotonic() - t_start
    logger.info(
        "scrape_watchlist_for_user: user_id=%d done — total inserted=%d across %d companies in %.2fs",
        user_id, inserted, len(watched), elapsed,
    )
    return inserted


async def scrape_for_all_users(get_db_context, shutdown_event=None) -> None:
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
        if shutdown_event and shutdown_event.is_set():
            logger.warning("scrape_for_all_users: shutdown signal — stopping before user_id=%d", uid)
            break
        try:
            async with get_db_context() as db:
                summary[uid] = await scrape_for_user(uid, db, shutdown_event=shutdown_event)
        except Exception as exc:
            logger.error(
                "scrape_for_all_users: user_id=%d failed: %s",
                uid, exc, exc_info=True,
            )
            summary[uid] = -1

        try:
            async with get_db_context() as db:
                await scrape_watchlist_for_user(uid, db)
        except Exception as exc:
            logger.error(
                "scrape_for_all_users: watchlist scrape for user_id=%d failed: %s",
                uid, exc, exc_info=True,
            )

    elapsed = time.monotonic() - t_start
    logger.info(
        "scrape_for_all_users: done in %.2fs — per-user new jobs: %s",
        elapsed,
        {f"user_{uid}": count for uid, count in summary.items()},
    )

    from app.pipeline.industry_backfill import backfill_industries
    try:
        async with get_db_context() as db:
            classified = await backfill_industries(db)
        logger.info("scrape_for_all_users: industry backfill complete — %d job(s) classified", classified)
    except Exception:
        logger.exception("scrape_for_all_users: industry backfill failed — scorer will skip unclassified jobs")
