"""
Background LLM scorer loop.

Runs continuously as an asyncio task. Picks the oldest unscored job_posting
per user, scores it against the user's profile via the research agent, writes
the result back. Sleeps 30s between jobs, 5 min when the queue is empty.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.modules.agents.research_agent import run_research_agent
from app.modules.agents.router import _load_profile
from app.shared.schemas import AgentError

logger = logging.getLogger(__name__)

SLEEP_BETWEEN_JOBS = 30       # seconds between scoring each job
SLEEP_QUEUE_EMPTY  = 300      # seconds to wait when no unscored jobs remain


async def _build_feedback_examples(db: AsyncSession, user_id: int) -> str:
    """
    Fetch up to 5 relevant and 5 not_relevant feedback rows for the user and
    format them as few-shot examples for the LLM prompt.
    Returns an empty string when the user has no feedback yet.
    """
    rows = await db.execute(
        text("""
            SELECT job_title, company, relevance
            FROM job_feedback
            WHERE user_id = :uid
            ORDER BY created_at DESC
            LIMIT 10
        """),
        {"uid": user_id},
    )
    feedback = rows.mappings().all()
    if not feedback:
        return ""

    relevant     = [f for f in feedback if f["relevance"] == "relevant"][:5]
    not_relevant = [f for f in feedback if f["relevance"] == "not_relevant"][:5]

    lines = ["User feedback on past jobs (use as calibration signal for scoring):"]
    if relevant:
        lines.append("Jobs marked RELEVANT (good fit for this user):")
        for f in relevant:
            lines.append(f"  + {f['job_title']} at {f['company']}")
    if not_relevant:
        lines.append("Jobs marked NOT RELEVANT (poor fit for this user):")
        for f in not_relevant:
            lines.append(f"  - {f['job_title']} at {f['company']}")

    return "\n".join(lines)


async def score_next_job(db: AsyncSession) -> bool:
    """
    Pick one unscored job (oldest posted_at first), score it, write back.
    Returns True if a job was processed, False if queue was empty.
    """
    row = await db.execute(
        text("""
            SELECT jp.id, jp.user_id, jp.title, jp.company, jp.url,
                   jp.description, jp.inferred_industries
            FROM job_postings jp
            WHERE jp.scored = 0
            ORDER BY jp.posted_at ASC, jp.scraped_at ASC
            LIMIT 1
        """)
    )
    job_row = row.mappings().first()
    if not job_row:
        return False

    job_id   = job_row["id"]
    user_id  = job_row["user_id"]
    logger.info("llm_scorer: scoring job_id=%d (%s @ %s) for user_id=%d",
                job_id, job_row["title"], job_row["company"], user_id)

    profile = await _load_profile(db, user_id)

    feedback_examples = await _build_feedback_examples(db, user_id)

    job_dict = {
        "title":               job_row["title"],
        "company":             job_row["company"],
        "url":                 job_row["url"],
        "description":         job_row["description"] or "",
        "inferred_industries": json.loads(job_row["inferred_industries"] or "[]"),
    }

    try:
        result, _ = await run_research_agent(
            profile=profile,
            job_postings=[job_dict],
            search_filters={},
            db=db,
            user_id=user_id,
            feedback_examples=feedback_examples,
        )
    except Exception as exc:
        logger.error("llm_scorer: agent failed for job_id=%d: %s", job_id, exc)
        # Mark scored so we don't retry a broken job forever
        await db.execute(
            text("UPDATE job_postings SET scored=1, scored_at=:now WHERE id=:id"),
            {"now": datetime.now(timezone.utc).isoformat(), "id": job_id},
        )
        await db.commit()
        return True

    if isinstance(result, AgentError) or not result.opportunities:
        logger.warning("llm_scorer: no output for job_id=%d, marking scored", job_id)
        await db.execute(
            text("UPDATE job_postings SET scored=1, scored_at=:now WHERE id=:id"),
            {"now": datetime.now(timezone.utc).isoformat(), "id": job_id},
        )
        await db.commit()
        return True

    opp = result.opportunities[0]
    await db.execute(
        text("""
            UPDATE job_postings SET
                scored      = 1,
                fit_score   = :fit_score,
                reasons     = :reasons,
                risks       = :risks,
                key_keywords = :keywords,
                scored_at   = :now
            WHERE id = :id
        """),
        {
            "fit_score": opp.fit_score,
            "reasons":   json.dumps(opp.reasons),
            "risks":     json.dumps(opp.risks),
            "keywords":  json.dumps(opp.key_keywords),
            "now":       datetime.now(timezone.utc).isoformat(),
            "id":        job_id,
        },
    )
    await db.commit()
    logger.info("llm_scorer: job_id=%d scored fit=%.2f", job_id, opp.fit_score)
    return True


async def run_scorer_loop(get_db_fn) -> None:
    """
    Infinite loop — call score_next_job() until queue is empty, then sleep.
    get_db_fn is a callable that returns an async context manager yielding a DB session.
    """
    logger.info("llm_scorer: loop started")
    while True:
        try:
            async with get_db_fn() as db:
                had_work = await score_next_job(db)
            sleep_secs = SLEEP_BETWEEN_JOBS if had_work else SLEEP_QUEUE_EMPTY
        except Exception as exc:
            logger.error("llm_scorer: unexpected error: %s", exc)
            sleep_secs = SLEEP_BETWEEN_JOBS

        await asyncio.sleep(sleep_secs)
