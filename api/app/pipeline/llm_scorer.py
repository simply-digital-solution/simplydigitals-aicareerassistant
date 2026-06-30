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

SLEEP_BETWEEN_BATCHES = 5     # seconds between scoring jobs
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


async def _pick_next_job(db: AsyncSession) -> dict | None:
    """
    SELECT the next job to score — shared by both the direct path and the
    controller-enqueue path. Returns a mapping dict or None if queue is empty.

    Users who have reached their daily scoring limit are excluded so that
    a capped user does not block other users' jobs from being picked.
    """
    settings = get_settings()
    new_user_limit      = int(settings.new_user_scoring_limit)
    existing_user_limit = int(settings.max_scorings_per_user_per_day)
    rows = await db.execute(
        text(f"""
            WITH user_usage AS (
                SELECT user_id,
                       COALESCE(SUM(jobs_scored) FILTER (WHERE date = CURRENT_DATE), 0) AS scored_today,
                       COALESCE(SUM(jobs_scored), 0) AS lifetime_total
                FROM daily_scoring_usage
                GROUP BY user_id
            ),
            user_limit AS (
                SELECT u.id AS user_id,
                       CASE
                           WHEN COALESCE(uu.lifetime_total, 0) = 0 THEN {new_user_limit}
                           ELSE {existing_user_limit}
                       END AS daily_limit,
                       COALESCE(uu.scored_today, 0) AS scored_today
                FROM users u
                LEFT JOIN user_usage uu ON uu.user_id = u.id
            )
            SELECT ujp.id AS ujp_id, ujp.user_id, jp.id AS jp_id,
                   jp.title, jp.company, jp.url,
                   jp.description, jp.inferred_industries
            FROM user_job_postings ujp
            JOIN job_postings jp ON jp.id = ujp.job_posting_id
            JOIN users u ON u.id = ujp.user_id
            JOIN user_limit ul ON ul.user_id = ujp.user_id
            WHERE u.scoring_suspended = false
              AND ul.scored_today < ul.daily_limit
              AND (
                -- New unscored job
                (ujp.scored = false AND ujp.rescoring = false AND (
                  ujp.score_error IS NULL
                  OR ujp.scored_at < NOW() - INTERVAL '30 minutes'
                  OR ujp.scored_at IS NULL
                ))
                OR
                -- Pending rescore (card stays visible with spinner)
                (ujp.scored = true AND ujp.rescoring = true)
              )
              AND NOT EXISTS (
                SELECT 1 FROM applications a
                WHERE a.job_posting_id = jp.id
                  AND a.user_id = ujp.user_id
                  AND a.status IN ('applied', 'interviewing', 'offered', 'rejected', 'withdrawn')
              )
            ORDER BY ujp.rescoring DESC, jp.posted_at DESC, jp.scraped_at DESC
            LIMIT 1
        """),
        {},
    )
    job_rows = rows.mappings().all()
    return job_rows[0] if job_rows else None


async def score_next_batch(db: AsyncSession) -> bool:
    """
    Pick the next unscored job and process it.

    When enable_llm_traffic_controller=True: enqueues (user_id, job_id) into
    the LLMTrafficController and returns True immediately (non-blocking).

    When enable_llm_traffic_controller=False (default): scores the job directly
    via run_research_agent — identical to the original behaviour.

    Returns True if a job was found, False if the queue was empty.
    """
    job_row = await _pick_next_job(db)
    if not job_row:
        return False

    user_id = job_row["user_id"]
    jp_id   = job_row["jp_id"]

    if get_settings().enable_llm_traffic_controller:
        # Controller path — enqueue and return; dispatcher handles the LLM call
        from app.shared.llm_traffic_controller import get_controller
        controller = get_controller()
        if controller is not None:
            enqueued = controller.enqueue(user_id=user_id, job_id=jp_id)
            if enqueued:
                logger.info(
                    "llm_scorer: enqueued job_id=%d for user_id=%d (queue_size=%d)",
                    jp_id, user_id, controller.queue_size,
                )
            else:
                logger.warning("llm_scorer: controller queue full — dropping job_id=%d", jp_id)
            return True
        else:
            logger.warning("llm_scorer: controller flag on but controller not initialised — falling back to direct path")

    # Direct path (flag off, or controller not available) — unchanged behaviour
    logger.info("llm_scorer: scoring job_id=%d for user_id=%d", jp_id, user_id)

    profile = await _load_profile(db, user_id)
    feedback_examples = await _build_feedback_examples(db, user_id)

    job_dict = {
        "job_id":              jp_id,
        "title":               job_row["title"],
        "company":             job_row["company"],
        "url":                 job_row["url"],
        "description":         job_row["description"] or "",
        "inferred_industries": json.loads(job_row["inferred_industries"] or "[]"),
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
        )
        logger.info("llm_scorer: LLM call completed in %.1fs", time.monotonic() - t_start)
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("llm_scorer: job_id=%d failed after %.1fs: %s", jp_id, time.monotonic() - t_start, error_msg)
        await db.execute(
            text("UPDATE user_job_postings SET scored=false, rescoring=false, score_error=:err, scored_at=:now WHERE job_posting_id=:jid AND user_id=:uid"),
            {"err": error_msg, "now": now_utc(), "jid": jp_id, "uid": user_id},
        )
        await db.commit()
        return True

    if isinstance(result, AgentError):
        error_msg = result.error
        logger.warning("llm_scorer: agent error for job_id=%d: %s", jp_id, error_msg)
        await db.execute(
            text("UPDATE user_job_postings SET scored=false, rescoring=false, score_error=:err, scored_at=:now WHERE job_posting_id=:jid AND user_id=:uid"),
            {"err": error_msg, "now": now_utc(), "jid": jp_id, "uid": user_id},
        )
        await db.commit()
        return True

    single_model = meta.get("model")
    returned = {opp.job_id: opp for opp in result.opportunities}
    opp = returned.get(jp_id)
    if opp is None:
        logger.warning("llm_scorer: job_id=%d missing from LLM response", jp_id)
        await db.execute(
            text("UPDATE user_job_postings SET scored=false, rescoring=false, score_error=:err, scored_at=:now WHERE job_posting_id=:jid AND user_id=:uid"),
            {"err": "Missing from LLM response", "now": now_utc(), "jid": jp_id, "uid": user_id},
        )
        await db.commit()
        return True

    await _write_score(db, jp_id, user_id, opp, model=single_model)
    await db.execute(
        text("UPDATE job_postings SET inferred_industries=:ind WHERE id=:id"),
        {"ind": json.dumps(opp.inferred_industries), "id": jp_id},
    )
    await _increment_scorings_today(db, user_id, 1)
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
    Score a specific list of jobs (job_postings.id) one at a time — used by bulk rescore endpoint.
    user_id scopes ownership check; if omitted, looks up via user_job_postings.
    Returns a dict mapping job_id → True (scored) / False (failed/missing).
    """
    if not job_ids:
        return {}

    results: dict[int, bool] = {}
    for jid in job_ids:
        results[jid] = await score_single_job(db, jid, user_id=user_id)
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
