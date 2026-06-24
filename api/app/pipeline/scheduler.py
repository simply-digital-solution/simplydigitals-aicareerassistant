"""
Scheduler — APScheduler cron jobs + scorer loop launcher.

Crons:
  05:00 SGT daily  → scrape_for_all_users()
  06:00 SGT daily  → suspend_inactive_users()
Loop:
  continuous asyncio task → run_scorer_loop()
"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_scorer_task: asyncio.Task | None = None


async def _run_daily_scrape() -> None:
    from app.shared.database import get_db_context
    from app.pipeline.daily_scrape import scrape_for_all_users
    logger.info("scheduler: daily scrape triggered at %s", __import__('datetime').datetime.now().isoformat(timespec='seconds'))
    await scrape_for_all_users(get_db_context)
    if _scheduler:
        job = _scheduler.get_job("daily_scrape")
        if job and job.next_run_time:
            logger.info("scheduler: next scrape scheduled at %s", job.next_run_time.isoformat(timespec='seconds'))


async def _run_daily_suspension() -> None:
    from app.shared.database import get_db_context
    from app.pipeline.suspension import suspend_inactive_users
    logger.info("scheduler: daily suspension check triggered")
    async with get_db_context() as db:
        suspended = await suspend_inactive_users(db)
    logger.info("scheduler: suspension check done — %d user(s) suspended", len(suspended))


async def _run_daily_job_cleanup() -> None:
    from app.shared.database import get_db_context
    from app.pipeline.job_cleanup import purge_stale_research_jobs
    logger.info("scheduler: daily research-job cleanup triggered")
    async with get_db_context() as db:
        deleted = await purge_stale_research_jobs(db)
    logger.info("scheduler: cleanup done — %d stale job(s) deleted", deleted)


def start(get_db_context_fn) -> None:
    """Start the scheduler and scorer loop. Call once from app lifespan."""
    global _scheduler, _scorer_task

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_daily_scrape,
        trigger=CronTrigger(hour=5, minute=0, timezone="Asia/Singapore"),
        id="daily_scrape",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        _run_daily_suspension,
        trigger=CronTrigger(hour=6, minute=0, timezone="Asia/Singapore"),
        id="daily_suspension",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        _run_daily_job_cleanup,
        trigger=CronTrigger(hour=4, minute=0, timezone="Asia/Singapore"),
        id="daily_job_cleanup",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info("scheduler: started — scrape 05:00 SGT, suspension 06:00 SGT, job cleanup 04:00 SGT")

    from app.pipeline.llm_scorer import run_scorer_loop
    _scorer_task = asyncio.create_task(run_scorer_loop(get_db_context_fn))
    logger.info("scheduler: LLM scorer loop started")


def stop() -> None:
    """Graceful shutdown — call from app lifespan teardown."""
    global _scheduler, _scorer_task
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    if _scorer_task:
        _scorer_task.cancel()
        _scorer_task = None
    logger.info("scheduler: stopped")
