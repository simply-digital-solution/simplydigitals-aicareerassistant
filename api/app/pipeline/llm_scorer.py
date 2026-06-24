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
from app.shared.sql_compat import now_utc, today_utc

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.modules.agents.research_agent import run_research_agent
from app.modules.agents.router import _load_profile
from app.shared.config import get_settings
from app.shared.schemas import AgentError

logger = logging.getLogger(__name__)

SLEEP_BETWEEN_BATCHES = 30    # seconds between scoring batches
SLEEP_QUEUE_EMPTY     = 300   # seconds to wait when no unscored jobs remain


async def _get_scorings_today(db: AsyncSession, user_id: int) -> int:
    """Return how many jobs this user has already had scored today."""
    today = today_utc()
    row = await db.execute(
        text("SELECT jobs_scored FROM daily_scoring_usage WHERE user_id=:uid AND date=:date"),
        {"uid": user_id, "date": today},
    )
    result = row.fetchone()
    return result[0] if result else 0


async def _increment_scorings_today(db: AsyncSession, user_id: int, count: int) -> None:
    """Increment the daily scoring counter for the user by count."""
    today = today_utc()
    await db.execute(
        text("""
            INSERT INTO daily_scoring_usage (user_id, date, jobs_scored, created_at)
            VALUES (:uid, :date, :count, :now)
            ON CONFLICT(user_id, date) DO UPDATE SET
                jobs_scored = daily_scoring_usage.jobs_scored + excluded.jobs_scored
        """),
        {"uid": user_id, "date": today, "count": count, "now": now_utc()},
    )


async def _get_daily_limit(db: AsyncSession, user_id: int) -> int:
    """
    Return the effective daily scoring limit for this user.
    New users (lifetime total = 0) get new_user_scoring_limit (250).
    Existing users get max_scorings_per_user_per_day (50).
    """
    settings = get_settings()
    row = await db.execute(
        text("SELECT COALESCE(SUM(jobs_scored), 0) FROM daily_scoring_usage WHERE user_id = :uid"),
        {"uid": user_id},
    )
    lifetime_total = row.fetchone()[0]
    if lifetime_total == 0:
        return settings.new_user_scoring_limit
    return settings.max_scorings_per_user_per_day


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
            SELECT ujp.id AS ujp_id, ujp.user_id, jp.id AS jp_id,
                   jp.title, jp.company, jp.url,
                   jp.description, jp.inferred_industries
            FROM user_job_postings ujp
            JOIN job_postings jp ON jp.id = ujp.job_posting_id
            JOIN users u ON u.id = ujp.user_id
            WHERE ujp.scored = false
              AND ujp.rescoring = false
              AND u.scoring_suspended = false
              AND (
                ujp.score_error IS NULL
                OR ujp.scored_at < NOW() - INTERVAL '30 minutes'
                OR ujp.scored_at IS NULL
              )
              AND NOT EXISTS (
                SELECT 1 FROM applications a
                WHERE a.job_posting_id = jp.id
                  AND a.user_id = ujp.user_id
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

    # Enforce daily scoring cap
    daily_limit = await _get_daily_limit(db, user_id)
    scored_today = await _get_scorings_today(db, user_id)
    remaining = daily_limit - scored_today
    if remaining <= 0:
        logger.info("llm_scorer: user_id=%d has reached daily scoring limit (%d)", user_id, daily_limit)
        return False
    job_rows = list(job_rows)[:remaining]

    # jp_id is the job_postings.id used as job_id in LLM calls
    jp_ids = [r["jp_id"] for r in job_rows]
    logger.info("llm_scorer: scoring batch of %d jobs %s for user_id=%d (%d/%d used today)",
                len(job_rows), jp_ids, user_id, scored_today, daily_limit)

    profile = await _load_profile(db, user_id)
    feedback_examples = await _build_feedback_examples(db, user_id)

    job_dicts = [
        {
            "job_id":              r["jp_id"],
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
        now = now_utc()
        for jp_id in jp_ids:
            await db.execute(
                text("UPDATE user_job_postings SET scored=false, score_error=:err, scored_at=:now WHERE job_posting_id=:jid AND user_id=:uid"),
                {"err": error_msg, "now": now, "jid": jp_id, "uid": user_id},
            )
        await db.commit()
        return True

    if isinstance(result, AgentError):
        error_msg = result.error
        logger.warning("llm_scorer: agent error for batch %s: %s", jp_ids, error_msg)
        now = now_utc()
        for jp_id in jp_ids:
            await db.execute(
                text("UPDATE user_job_postings SET scored=false, score_error=:err, scored_at=:now WHERE job_posting_id=:jid AND user_id=:uid"),
                {"err": error_msg, "now": now, "jid": jp_id, "uid": user_id},
            )
        await db.commit()
        return True

    # Match results by job_id (which is jp.id = job_postings.id)
    batch_model = meta.get("model")
    returned = {opp.job_id: opp for opp in result.opportunities}
    now = now_utc()
    scored_count = 0
    for jp_id in jp_ids:
        opp = returned.get(jp_id)
        if opp is None:
            logger.warning("llm_scorer: job_id=%d missing from batch response", jp_id)
            await db.execute(
                text("UPDATE user_job_postings SET scored=false, score_error=:err, scored_at=:now WHERE job_posting_id=:jid AND user_id=:uid"),
                {"err": "Missing from LLM batch response", "now": now, "jid": jp_id, "uid": user_id},
            )
            continue
        await _write_score(db, jp_id, user_id, opp, model=batch_model)
        # Also update inferred_industries on the shared job_postings row
        await db.execute(
            text("UPDATE job_postings SET inferred_industries=:ind WHERE id=:id"),
            {"ind": json.dumps(opp.inferred_industries), "id": jp_id},
        )
        scored_count += 1

    await _increment_scorings_today(db, user_id, scored_count)
    await db.commit()
    return True


async def _write_score(db: AsyncSession, job_posting_id: int, user_id: int, opp, model: str | None = None) -> None:
    """Write a scored opportunity to user_job_postings."""
    breakdown = [b.model_dump() for b in opp.scoring_breakdown] if opp.scoring_breakdown else []
    await db.execute(
        text("""
            UPDATE user_job_postings SET
                scored            = true,
                rescoring         = false,
                fit_score         = :fit_score,
                reasons           = :reasons,
                risks             = :risks,
                key_keywords      = :keywords,
                scoring_breakdown = :breakdown,
                recommendation    = :recommendation,
                scored_by_model   = :model,
                score_error       = NULL,
                scored_at         = :now
            WHERE job_posting_id = :jid AND user_id = :uid
        """),
        {
            "fit_score":      opp.fit_score,
            "reasons":        json.dumps(opp.reasons),
            "risks":          json.dumps(opp.risks),
            "keywords":       json.dumps(opp.key_keywords),
            "breakdown":      json.dumps(breakdown),
            "recommendation": opp.recommendation or None,
            "model":          model,
            "now":            now_utc(),
            "jid":            job_posting_id,
            "uid":            user_id,
        },
    )
    logger.info("llm_scorer: job_id=%d user_id=%d scored fit=%.2f model=%s", job_posting_id, user_id, opp.fit_score, model)


async def score_single_job(db: AsyncSession, job_id: int, user_id: int | None = None) -> bool:
    """
    Score a single job immediately — used by the rescore endpoint.
    job_id is the job_postings.id (content table).
    user_id is required; if omitted, we look it up from user_job_postings.
    Returns True if scoring succeeded, False if the job was not found.
    """
    # Fetch content + find which user owns this UJP row
    if user_id is None:
        row = await db.execute(
            text("""
                SELECT jp.id AS jp_id, ujp.user_id,
                       jp.title, jp.company, jp.url, jp.description, jp.inferred_industries
                FROM job_postings jp
                JOIN user_job_postings ujp ON ujp.job_posting_id = jp.id
                WHERE jp.id = :id
                LIMIT 1
            """),
            {"id": job_id},
        )
    else:
        row = await db.execute(
            text("""
                SELECT jp.id AS jp_id, ujp.user_id,
                       jp.title, jp.company, jp.url, jp.description, jp.inferred_industries
                FROM job_postings jp
                JOIN user_job_postings ujp ON ujp.job_posting_id = jp.id
                WHERE jp.id = :id AND ujp.user_id = :uid
            """),
            {"id": job_id, "uid": user_id},
        )
    job = row.mappings().first()
    if not job:
        return False

    resolved_user_id = job["user_id"]

    # Skip rescoring if the job has progressed to applied or beyond
    app_check = await db.execute(
        text("""
            SELECT 1 FROM applications
            WHERE job_posting_id = :id
              AND user_id = :uid
              AND status IN ('applied', 'interviewing', 'offered', 'rejected', 'withdrawn')
            LIMIT 1
        """),
        {"id": job_id, "uid": resolved_user_id},
    )
    if app_check.fetchone():
        logger.info("llm_scorer: skipping job_id=%d — application already in advanced status", job_id)
        return False

    # Enforce daily scoring cap
    daily_limit = await _get_daily_limit(db, resolved_user_id)
    scored_today = await _get_scorings_today(db, resolved_user_id)
    if scored_today >= daily_limit:
        logger.info("llm_scorer: user_id=%d daily limit reached (%d), skipping single rescore of job_id=%d",
                    resolved_user_id, daily_limit, job_id)
        return False

    logger.info("llm_scorer: scoring single job_id=%d for user_id=%d (%d/%d used today)",
                job_id, resolved_user_id, scored_today, daily_limit)

    # Mark in-progress — old score stays visible until new one arrives
    await db.execute(
        text("UPDATE user_job_postings SET rescoring=true, score_error=NULL WHERE job_posting_id=:jid AND user_id=:uid"),
        {"jid": job_id, "uid": resolved_user_id},
    )
    await db.commit()

    profile = await _load_profile(db, resolved_user_id)
    feedback_examples = await _build_feedback_examples(db, resolved_user_id)

    job_dict = {
        "job_id":              job["jp_id"],
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
            user_id=resolved_user_id,
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
            text("UPDATE user_job_postings SET rescoring=false, score_error=:err WHERE job_posting_id=:jid AND user_id=:uid"),
            {"err": error_msg, "jid": job_id, "uid": resolved_user_id},
        )
        await db.commit()
        return False

    if isinstance(result, AgentError):
        logger.warning("llm_scorer: single job_id=%d agent error: %s", job_id, result.error)
        await db.execute(
            text("UPDATE user_job_postings SET rescoring=false, score_error=:err WHERE job_posting_id=:jid AND user_id=:uid"),
            {"err": result.error, "jid": job_id, "uid": resolved_user_id},
        )
        await db.commit()
        return False

    single_model = meta.get("model")
    returned = {opp.job_id: opp for opp in result.opportunities}
    opp = returned.get(job_id)
    if opp is None:
        logger.warning("llm_scorer: job_id=%d missing from single response", job_id)
        await db.execute(
            text("UPDATE user_job_postings SET rescoring=false, score_error=:err WHERE job_posting_id=:jid AND user_id=:uid"),
            {"err": "Missing from LLM response", "jid": job_id, "uid": resolved_user_id},
        )
        await db.commit()
        return False

    await _write_score(db, job_id, resolved_user_id, opp, model=single_model)
    # Update inferred_industries on the shared job_postings row
    await db.execute(
        text("UPDATE job_postings SET inferred_industries=:ind WHERE id=:id"),
        {"ind": json.dumps(opp.inferred_industries), "id": job_id},
    )
    await _increment_scorings_today(db, resolved_user_id, 1)
    await db.commit()
    return True


async def score_jobs_by_ids(db: AsyncSession, job_ids: list[int], user_id: int | None = None) -> dict[int, bool]:
    """
    Score a specific list of jobs (job_postings.id) in one LLM call — used by bulk rescore endpoint.
    user_id scopes ownership check; if omitted, looks up via user_job_postings.
    Returns a dict mapping job_id → True (scored) / False (failed/missing).
    """
    if not job_ids:
        return {}

    placeholders = ",".join(f":id{i}" for i in range(len(job_ids)))
    params = {f"id{i}": jid for i, jid in enumerate(job_ids)}
    if user_id is not None:
        params["uid"] = user_id
        uid_filter = "AND ujp.user_id = :uid"
    else:
        uid_filter = ""

    rows = await db.execute(
        text(f"""
            SELECT jp.id AS jp_id, ujp.user_id,
                   jp.title, jp.company, jp.url, jp.description, jp.inferred_industries
            FROM job_postings jp
            JOIN user_job_postings ujp ON ujp.job_posting_id = jp.id
            WHERE jp.id IN ({placeholders}) {uid_filter}
        """),
        params,
    )
    job_rows = rows.mappings().all()
    if not job_rows:
        return {jid: False for jid in job_ids}

    resolved_user_id = user_id or job_rows[0]["user_id"]
    found_ids = {r["jp_id"] for r in job_rows}

    # Exclude jobs whose application has progressed to applied or beyond
    if found_ids:
        adv_placeholders = ",".join(f":aid{i}" for i in range(len(found_ids)))
        adv_params = {f"aid{i}": jid for i, jid in enumerate(found_ids)}
        adv_params["uid"] = resolved_user_id
        adv_rows = await db.execute(
            text(f"""
                SELECT DISTINCT job_posting_id FROM applications
                WHERE job_posting_id IN ({adv_placeholders})
                  AND user_id = :uid
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

    # Enforce daily scoring cap
    daily_limit = await _get_daily_limit(db, resolved_user_id)
    scored_today = await _get_scorings_today(db, resolved_user_id)
    remaining = daily_limit - scored_today
    if remaining <= 0:
        logger.info("llm_scorer: user_id=%d daily limit reached (%d), skipping bulk rescore", resolved_user_id, daily_limit)
        return {jid: False for jid in job_ids}
    if len(found_ids) > remaining:
        logger.info("llm_scorer: trimming bulk rescore from %d to %d (daily limit)", len(found_ids), remaining)
        found_ids = set(list(found_ids)[:remaining])

    logger.info("llm_scorer: bulk rescoring %d jobs for user_id=%d (%d/%d used today)",
                len(found_ids), resolved_user_id, scored_today, daily_limit)

    # Mark as in-progress — old score fields untouched so jobs stay visible
    for jid in found_ids:
        await db.execute(
            text("UPDATE user_job_postings SET rescoring=true, score_error=NULL WHERE job_posting_id=:jid AND user_id=:uid"),
            {"jid": jid, "uid": resolved_user_id},
        )
    await db.commit()

    profile = await _load_profile(db, resolved_user_id)
    feedback_examples = await _build_feedback_examples(db, resolved_user_id)

    job_dicts = [
        {
            "job_id":              r["jp_id"],
            "title":               r["title"],
            "company":             r["company"],
            "url":                 r["url"],
            "description":         r["description"] or "",
            "inferred_industries": json.loads(r["inferred_industries"] or "[]"),
        }
        for r in job_rows
        if r["jp_id"] in found_ids
    ]

    results: dict[int, bool] = {jid: False for jid in job_ids}

    t_start = time.monotonic()
    try:
        result, meta = await run_research_agent(
            profile=profile,
            job_postings=job_dicts,
            search_filters={},
            db=db,
            user_id=resolved_user_id,
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
                text("UPDATE user_job_postings SET rescoring=false, score_error=:err WHERE job_posting_id=:jid AND user_id=:uid"),
                {"err": error_msg, "jid": jid, "uid": resolved_user_id},
            )
        await db.commit()
        return results

    if isinstance(result, AgentError):
        logger.warning("llm_scorer: bulk rescore agent error: %s", result.error)
        for jid in found_ids:
            await db.execute(
                text("UPDATE user_job_postings SET rescoring=false, score_error=:err WHERE job_posting_id=:jid AND user_id=:uid"),
                {"err": result.error, "jid": jid, "uid": resolved_user_id},
            )
        await db.commit()
        return results

    bulk_model = meta.get("model")
    returned = {opp.job_id: opp for opp in result.opportunities}
    scored_count = 0
    for jid in found_ids:
        opp = returned.get(jid)
        if opp is None:
            logger.warning("llm_scorer: job_id=%d missing from bulk response", jid)
            await db.execute(
                text("UPDATE user_job_postings SET rescoring=false, score_error=:err WHERE job_posting_id=:jid AND user_id=:uid"),
                {"err": "Missing from LLM bulk response", "jid": jid, "uid": resolved_user_id},
            )
        else:
            await _write_score(db, jid, resolved_user_id, opp, model=bulk_model)
            await db.execute(
                text("UPDATE job_postings SET inferred_industries=:ind WHERE id=:id"),
                {"ind": json.dumps(opp.inferred_industries), "id": jid},
            )
            results[jid] = True
            scored_count += 1

    await _increment_scorings_today(db, resolved_user_id, scored_count)
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
