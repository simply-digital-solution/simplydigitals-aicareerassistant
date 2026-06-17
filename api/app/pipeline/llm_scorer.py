"""
Background LLM scorer loop.

Runs continuously as an asyncio task. Picks the oldest unscored job_posting
per user, scores it against the user's profile via the research agent, writes
the result back. Sleeps 30s between jobs, 5 min when the queue is empty.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.modules.agents.research_agent import run_research_agent
from app.modules.agents.router import _load_profile
from app.shared.config import get_settings
from app.shared.schemas import AgentError

logger = logging.getLogger(__name__)

SLEEP_BETWEEN_BATCHES = 30    # seconds between scoring batches
SLEEP_QUEUE_EMPTY     = 300   # seconds to wait when no unscored jobs remain


async def _build_feedback_examples(db: AsyncSession, user_id: int) -> str:
    """
    Fetch up to 5 relevant and 5 not_relevant feedback rows for the user and
    format them as few-shot examples for the LLM prompt.
    Returns an empty string when the user has no feedback yet.
    """
    rows = await db.execute(
        text("""
            SELECT job_title, company, relevance, reason
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
            reason_suffix = f" (reason: {f['reason']})" if f["reason"] else ""
            lines.append(f"  - {f['job_title']} at {f['company']}{reason_suffix}")

    return "\n".join(lines)


async def score_next_batch(db: AsyncSession) -> bool:
    """
    Pick up to batch_size unscored jobs, score them in one LLM call, write back.
    Matches results by job_id — missing or failed jobs are marked individually.
    Returns True if any jobs were processed, False if queue was empty.
    """
    batch_size = get_settings().scorer_batch_size

    rows = await db.execute(
        text("""
            SELECT jp.id, jp.user_id, jp.title, jp.company, jp.url,
                   jp.description, jp.inferred_industries
            FROM job_postings jp
            WHERE jp.scored = 0
              AND jp.score_error IS NULL
            ORDER BY jp.posted_at ASC, jp.scraped_at ASC
            LIMIT :batch_size
        """),
        {"batch_size": batch_size},
    )
    job_rows = rows.mappings().all()
    if not job_rows:
        return False

    # All jobs in a batch must belong to the same user (scorer loops per-user queue)
    user_id = job_rows[0]["user_id"]
    job_ids = [r["id"] for r in job_rows]
    logger.info("llm_scorer: scoring batch of %d jobs %s for user_id=%d", len(job_rows), job_ids, user_id)

    profile = await _load_profile(db, user_id)
    feedback_examples = await _build_feedback_examples(db, user_id)

    job_dicts = [
        {
            "job_id":              r["id"],
            "title":               r["title"],
            "company":             r["company"],
            "url":                 r["url"],
            "description":         r["description"] or "",
            "inferred_industries": json.loads(r["inferred_industries"] or "[]"),
        }
        for r in job_rows
    ]

    t_start = time.monotonic()
    try:
        result, _ = await run_research_agent(
            profile=profile,
            job_postings=job_dicts,
            search_filters={},
            db=db,
            user_id=user_id,
            request_type="scoring",
            feedback_examples=feedback_examples,
            full_description=True,
        )
        logger.info("llm_scorer: batch LLM call completed in %.1fs", time.monotonic() - t_start)
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("llm_scorer: batch failed after %.1fs: %s", time.monotonic() - t_start, error_msg)
        for jid in job_ids:
            await db.execute(
                text("UPDATE job_postings SET scored=0, score_error=:err WHERE id=:id"),
                {"err": error_msg, "id": jid},
            )
        await db.commit()
        return True

    if isinstance(result, AgentError):
        error_msg = result.error
        logger.warning("llm_scorer: agent error for batch %s: %s", job_ids, error_msg)
        for jid in job_ids:
            await db.execute(
                text("UPDATE job_postings SET scored=0, score_error=:err WHERE id=:id"),
                {"err": error_msg, "id": jid},
            )
        await db.commit()
        return True

    # Match results by job_id
    returned = {opp.job_id: opp for opp in result.opportunities}
    for jid in job_ids:
        opp = returned.get(jid)
        if opp is None:
            logger.warning("llm_scorer: job_id=%d missing from batch response", jid)
            await db.execute(
                text("UPDATE job_postings SET scored=0, score_error=:err WHERE id=:id"),
                {"err": "Missing from LLM batch response", "id": jid},
            )
            continue

        breakdown = [b.model_dump() for b in opp.scoring_breakdown] if opp.scoring_breakdown else []
        await db.execute(
            text("""
                UPDATE job_postings SET
                    scored             = 1,
                    fit_score          = :fit_score,
                    reasons            = :reasons,
                    risks              = :risks,
                    key_keywords       = :keywords,
                    scoring_breakdown  = :breakdown,
                    recommendation     = :recommendation,
                    score_error        = NULL,
                    scored_at          = :now
                WHERE id = :id
            """),
            {
                "fit_score":      opp.fit_score,
                "reasons":        json.dumps(opp.reasons),
                "risks":          json.dumps(opp.risks),
                "keywords":       json.dumps(opp.key_keywords),
                "breakdown":      json.dumps(breakdown),
                "recommendation": opp.recommendation or None,
                "now":            datetime.now(timezone.utc).isoformat(),
                "id":             jid,
            },
        )
        logger.info("llm_scorer: job_id=%d scored fit=%.2f", jid, opp.fit_score)

    await db.commit()
    return True


async def run_scorer_loop(get_db_fn) -> None:
    """
    Infinite loop — call score_next_batch() until queue is empty, then sleep.
    get_db_fn is a callable that returns an async context manager yielding a DB session.
    """
    logger.info("llm_scorer: loop started")
    while True:
        try:
            async with get_db_fn() as db:
                had_work = await score_next_batch(db)
            sleep_secs = SLEEP_BETWEEN_BATCHES if had_work else SLEEP_QUEUE_EMPTY
        except Exception as exc:
            logger.error("llm_scorer: unexpected error: %s", exc)
            sleep_secs = SLEEP_BETWEEN_BATCHES

        await asyncio.sleep(sleep_secs)
