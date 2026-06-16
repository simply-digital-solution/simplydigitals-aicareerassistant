"""
Scheduler — APScheduler cron job + scorer loop launcher.

Cron:  daily at 07:00 Asia/Singapore  → scrape_for_all_users()
Loop:  continuous asyncio task         → run_scorer_loop()
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
    async with get_db_context() as db:
        await scrape_for_all_users(db)
    if _scheduler:
        job = _scheduler.get_job("daily_scrape")
        if job and job.next_run_time:
            logger.info("scheduler: next scrape scheduled at %s", job.next_run_time.isoformat(timespec='seconds'))


def start(get_db_context_fn) -> None:
    """Start the scheduler and scorer loop. Call once from app lifespan."""
    global _scheduler, _scorer_task

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_daily_scrape,
        trigger=CronTrigger(hour=7, minute=0, timezone="Asia/Singapore"),
        id="daily_scrape",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info("scheduler: started — daily scrape at 07:00 SGT")

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
