"""
Score every idle/failed/in-progress job across all users, respecting each
user's daily scoring quota. Wraps the same score_next_batch picker used by
the production scheduler's background scorer loop.

Usage:
  cd api
  poetry run python scripts/score_idle_jobs.py
"""
import asyncio
import logging

from app.pipeline.llm_scorer import score_next_batch
from app.shared.database import get_db_context

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def score_all_idle_jobs() -> int:
    """Repeatedly score the next eligible job until the queue is empty. Returns count scored."""
    scored = 0
    while True:
        async with get_db_context() as db:
            had_work = await score_next_batch(db)
        if not had_work:
            break
        scored += 1
        if scored % 10 == 0:
            logger.info("scored %d so far...", scored)
    return scored


async def main() -> None:
    scored = await score_all_idle_jobs()
    print(f"done — scored {scored} jobs")


if __name__ == "__main__":
    asyncio.run(main())
