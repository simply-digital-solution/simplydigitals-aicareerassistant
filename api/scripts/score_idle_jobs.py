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

from sqlalchemy import text

from app.pipeline.llm_scorer import score_next_batch
from app.shared.database import get_db_context
from app.shared.sql_compat import now_utc

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


async def _find_failures_since(run_started_at) -> list[dict]:
    """Jobs that ended up scoring_status='failed' during this run, for the
    script's own summary — score_next_batch already writes score_error per
    row, this just surfaces it instead of leaving it to be found later."""
    async with get_db_context() as db:
        rows = await db.execute(
            text("""
                SELECT jp.title, jp.company, ujp.score_error
                FROM user_job_postings ujp
                JOIN job_postings jp ON jp.id = ujp.job_posting_id
                WHERE ujp.scoring_status = 'failed'
                  AND ujp.scored_at >= :started_at
                ORDER BY ujp.scored_at
            """),
            {"started_at": run_started_at},
        )
        return [dict(r) for r in rows.mappings()]


async def main() -> None:
    run_started_at = now_utc()
    scored = await score_all_idle_jobs()
    print(f"done — scored {scored} jobs")

    failures = await _find_failures_since(run_started_at)
    if failures:
        print(f"\n⚠ ERRORS: {len(failures)} job(s) failed to score")
        for f in failures:
            print(f"  PIPELINE_ERROR: {f['title']!r} ({f['company']!r}): {f['score_error']}")


if __name__ == "__main__":
    asyncio.run(main())
