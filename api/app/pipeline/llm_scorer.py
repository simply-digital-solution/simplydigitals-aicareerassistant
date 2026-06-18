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
              AND jp.rescoring = 0
              AND (
                jp.score_error IS NULL
                OR jp.scored_at < datetime('now', '-30 minutes')
                OR jp.scored_at IS NULL
              )
              AND NOT EXISTS (
                SELECT 1 FROM applications a
                WHERE a.job_posting_id = jp.id
                  AND a.status IN ('applied', 'interviewing', 'offered', 'rejected', 'withdrawn')
              )
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
        result, meta = await run_research_agent(
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
        now = datetime.now(timezone.utc).isoformat()
        for jid in job_ids:
            await db.execute(
                text("UPDATE job_postings SET scored=0, score_error=:err, scored_at=:now WHERE id=:id"),
                {"err": error_msg, "now": now, "id": jid},
            )
        await db.commit()
        return True

    if isinstance(result, AgentError):
        error_msg = result.error
        logger.warning("llm_scorer: agent error for batch %s: %s", job_ids, error_msg)
        now = datetime.now(timezone.utc).isoformat()
        for jid in job_ids:
            await db.execute(
                text("UPDATE job_postings SET scored=0, score_error=:err, scored_at=:now WHERE id=:id"),
                {"err": error_msg, "now": now, "id": jid},
            )
        await db.commit()
        return True

    # Match results by job_id
    batch_model = meta.get("model")
    returned = {opp.job_id: opp for opp in result.opportunities}
    now = datetime.now(timezone.utc).isoformat()
    for jid in job_ids:
        opp = returned.get(jid)
        if opp is None:
            logger.warning("llm_scorer: job_id=%d missing from batch response", jid)
            await db.execute(
                text("UPDATE job_postings SET scored=0, score_error=:err, scored_at=:now WHERE id=:id"),
                {"err": "Missing from LLM batch response", "now": now, "id": jid},
            )
            continue
        await _write_score(db, jid, opp, model=batch_model)

    await db.commit()
    return True


async def _write_score(db: AsyncSession, job_id: int, opp, model: str | None = None) -> None:
    """Write a scored opportunity back to the DB (shared by batch and single scorer)."""
    breakdown = [b.model_dump() for b in opp.scoring_breakdown] if opp.scoring_breakdown else []
    await db.execute(
        text("""
            UPDATE job_postings SET
                scored               = 1,
                rescoring            = 0,
                fit_score            = :fit_score,
                reasons              = :reasons,
                risks                = :risks,
                key_keywords         = :keywords,
                scoring_breakdown    = :breakdown,
                recommendation       = :recommendation,
                inferred_industries  = :industries,
                scored_by_model      = :model,
                score_error          = NULL,
                scored_at            = :now
            WHERE id = :id
        """),
        {
            "fit_score":      opp.fit_score,
            "reasons":        json.dumps(opp.reasons),
            "risks":          json.dumps(opp.risks),
            "keywords":       json.dumps(opp.key_keywords),
            "breakdown":      json.dumps(breakdown),
            "recommendation": opp.recommendation or None,
            "industries":     json.dumps(opp.inferred_industries),
            "model":          model,
            "now":            datetime.now(timezone.utc).isoformat(),
            "id":             job_id,
        },
    )
    logger.info("llm_scorer: job_id=%d scored fit=%.2f model=%s", job_id, opp.fit_score, model)


async def score_single_job(db: AsyncSession, job_id: int) -> bool:
    """
    Score a single job immediately — used by the rescore endpoint.
    Returns True if scoring succeeded, False if the job was not found.
    """
    row = await db.execute(
        text("""
            SELECT id, user_id, title, company, url, description, inferred_industries
            FROM job_postings
            WHERE id = :id
        """),
        {"id": job_id},
    )
    job = row.mappings().first()
    if not job:
        return False

    # Skip rescoring if the job has progressed to applied or beyond
    app_check = await db.execute(
        text("""
            SELECT 1 FROM applications
            WHERE job_posting_id = :id
              AND status IN ('applied', 'interviewing', 'offered', 'rejected', 'withdrawn')
            LIMIT 1
        """),
        {"id": job_id},
    )
    if app_check.fetchone():
        logger.info("llm_scorer: skipping job_id=%d — application already in advanced status", job_id)
        return False

    user_id = job["user_id"]
    logger.info("llm_scorer: scoring single job_id=%d for user_id=%d", job_id, user_id)

    # Mark in-progress — old score stays visible until new one arrives
    await db.execute(
        text("UPDATE job_postings SET rescoring=1, score_error=NULL WHERE id=:id"),
        {"id": job_id},
    )
    await db.commit()

    profile = await _load_profile(db, user_id)
    feedback_examples = await _build_feedback_examples(db, user_id)

    job_dict = {
        "job_id":              job["id"],
        "title":               job["title"],
        "company":             job["company"],
        "url":                 job["url"],
        "description":         job["description"] or "",
        "inferred_industries": json.loads(job["inferred_industries"] or "[]"),
    }

    t_start = time.monotonic()
    try:
        result, meta = await run_research_agent(
            profile=profile,
            job_postings=[job_dict],
            search_filters={},
            db=db,
            user_id=user_id,
            request_type="scoring",
            feedback_examples=feedback_examples,
            full_description=True,
            max_self_corrections=0,
        )
        logger.info("llm_scorer: single job LLM call completed in %.1fs", time.monotonic() - t_start)
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("llm_scorer: single job_id=%d failed: %s", job_id, error_msg)
        await db.execute(
            text("UPDATE job_postings SET rescoring=0, score_error=:err WHERE id=:id"),
            {"err": error_msg, "id": job_id},
        )
        await db.commit()
        return False

    if isinstance(result, AgentError):
        logger.warning("llm_scorer: single job_id=%d agent error: %s", job_id, result.error)
        await db.execute(
            text("UPDATE job_postings SET rescoring=0, score_error=:err WHERE id=:id"),
            {"err": result.error, "id": job_id},
        )
        await db.commit()
        return False

    single_model = meta.get("model")
    returned = {opp.job_id: opp for opp in result.opportunities}
    opp = returned.get(job_id)
    if opp is None:
        logger.warning("llm_scorer: job_id=%d missing from single response", job_id)
        await db.execute(
            text("UPDATE job_postings SET rescoring=0, score_error=:err WHERE id=:id"),
            {"err": "Missing from LLM response", "id": job_id},
        )
        await db.commit()
        return False

    await _write_score(db, job_id, opp, model=single_model)
    await db.commit()
    return True


async def score_jobs_by_ids(db: AsyncSession, job_ids: list[int]) -> dict[int, bool]:
    """
    Score a specific list of jobs in one LLM call — used by bulk rescore endpoint.
    Returns a dict mapping job_id → True (scored) / False (failed/missing).
    Old scores are preserved until new ones arrive; failures set score_error only.
    """
    if not job_ids:
        return {}

    placeholders = ",".join(f":id{i}" for i in range(len(job_ids)))
    params = {f"id{i}": jid for i, jid in enumerate(job_ids)}
    rows = await db.execute(
        text(f"""
            SELECT id, user_id, title, company, url, description, inferred_industries
            FROM job_postings
            WHERE id IN ({placeholders})
        """),
        params,
    )
    job_rows = rows.mappings().all()
    if not job_rows:
        return {jid: False for jid in job_ids}

    user_id = job_rows[0]["user_id"]
    found_ids = {r["id"] for r in job_rows}

    # Exclude jobs whose application has progressed to applied or beyond
    if found_ids:
        adv_placeholders = ",".join(f":aid{i}" for i in range(len(found_ids)))
        adv_params = {f"aid{i}": jid for i, jid in enumerate(found_ids)}
        adv_rows = await db.execute(
            text(f"""
                SELECT DISTINCT job_posting_id FROM applications
                WHERE job_posting_id IN ({adv_placeholders})
                  AND status IN ('applied', 'interviewing', 'offered', 'rejected', 'withdrawn')
            """),
            adv_params,
        )
        advanced_ids = {r[0] for r in adv_rows.fetchall()}
        if advanced_ids:
            logger.info("llm_scorer: skipping %d job(s) in advanced status: %s", len(advanced_ids), advanced_ids)
            found_ids -= advanced_ids

    if not found_ids:
        return {jid: False for jid in job_ids}

    logger.info("llm_scorer: bulk rescoring %d jobs for user_id=%d", len(found_ids), user_id)

    # Mark as in-progress — old score fields untouched so jobs stay visible
    for jid in found_ids:
        await db.execute(
            text("UPDATE job_postings SET rescoring=1, score_error=NULL WHERE id=:id"),
            {"id": jid},
        )
    await db.commit()

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
        if r["id"] in found_ids
    ]

    results: dict[int, bool] = {jid: False for jid in job_ids}

    t_start = time.monotonic()
    try:
        result, meta = await run_research_agent(
            profile=profile,
            job_postings=job_dicts,
            search_filters={},
            db=db,
            user_id=user_id,
            request_type="scoring",
            feedback_examples=feedback_examples,
            full_description=True,
        )
        logger.info("llm_scorer: bulk rescore LLM call completed in %.1fs", time.monotonic() - t_start)
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("llm_scorer: bulk rescore failed: %s", error_msg)
        for jid in found_ids:
            await db.execute(
                text("UPDATE job_postings SET rescoring=0, score_error=:err WHERE id=:id"),
                {"err": error_msg, "id": jid},
            )
        await db.commit()
        return results

    if isinstance(result, AgentError):
        logger.warning("llm_scorer: bulk rescore agent error: %s", result.error)
        for jid in found_ids:
            await db.execute(
                text("UPDATE job_postings SET rescoring=0, score_error=:err WHERE id=:id"),
                {"err": result.error, "id": jid},
            )
        await db.commit()
        return results

    bulk_model = meta.get("model")
    returned = {opp.job_id: opp for opp in result.opportunities}
    for jid in found_ids:
        opp = returned.get(jid)
        if opp is None:
            logger.warning("llm_scorer: job_id=%d missing from bulk response", jid)
            await db.execute(
                text("UPDATE job_postings SET rescoring=0, score_error=:err WHERE id=:id"),
                {"err": "Missing from LLM bulk response", "id": jid},
            )
        else:
            await _write_score(db, jid, opp, model=bulk_model)
            results[jid] = True

    await db.commit()
    return results


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
