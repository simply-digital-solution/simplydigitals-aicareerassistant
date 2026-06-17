"""
Bulk resume generator.

Generates tailored resumes for a list of job IDs sequentially.
Rate limiting is handled globally by GeminiClient via gemini_rate_limiter —
no artificial sleep needed here.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.modules.agents.resume_generate_agent import run_resume_generate_agent
from app.shared.models import Profile
from app.shared.schemas import AgentError

logger = logging.getLogger(__name__)


async def generate_resumes_for_jobs(
    db: AsyncSession,
    job_ids: list[int],
    user_id: int,
) -> dict[int, bool]:
    """
    Generate tailored resumes for each job ID sequentially.
    Upserts each result to generated_resumes as it completes.
    Returns dict mapping job_id → True (success) / False (failed).
    """
    if not job_ids:
        return {}

    p_row = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = p_row.scalar_one_or_none()
    resume_text = (profile.resume_text or "") if profile else ""
    candidate_name = (profile.full_name or "") if profile else ""

    if not resume_text.strip():
        logger.warning("resume_generator: user_id=%d has no resume text", user_id)
        return {jid: False for jid in job_ids}

    # Fetch all job descriptions in one query
    placeholders = ",".join(f":id{i}" for i in range(len(job_ids)))
    params = {f"id{i}": jid for i, jid in enumerate(job_ids)}
    rows = await db.execute(
        text(f"SELECT id, description FROM job_postings WHERE id IN ({placeholders}) AND user_id = :uid"),
        {"uid": user_id, **params},
    )
    job_map = {r["id"]: r["description"] or "" for r in rows.mappings().all()}

    results: dict[int, bool] = {}

    for jid in job_ids:
        jd_text = job_map.get(jid, "")
        logger.info("resume_generator: generating resume for job_id=%d user_id=%d", jid, user_id)

        try:
            result, _ = await run_resume_generate_agent(
                resume_text=resume_text,
                jd_text=jd_text,
                candidate_name=candidate_name,
                db=db,
                user_id=user_id,
            )
        except Exception as exc:
            logger.error("resume_generator: job_id=%d failed: %s", jid, exc)
            results[jid] = False
            continue

        if isinstance(result, AgentError):
            logger.warning("resume_generator: job_id=%d agent error: %s", jid, result.error)
            results[jid] = False
            continue

        now = datetime.now(timezone.utc).isoformat()
        resume_json = result.model_dump_json()

        # Fetch linked application_id if exists
        app_row = await db.execute(
            text("""
                SELECT id FROM applications
                WHERE job_posting_id = :jid AND user_id = :uid AND status = 'selected'
                LIMIT 1
            """),
            {"jid": jid, "uid": user_id},
        )
        app = app_row.mappings().first()
        application_id = app["id"] if app else None

        await db.execute(
            text("""
                INSERT INTO generated_resumes
                    (user_id, job_posting_id, application_id, resume_json, created_at, updated_at)
                VALUES
                    (:uid, :jid, :aid, :resume_json, :now, :now)
                ON CONFLICT (user_id, job_posting_id) DO UPDATE SET
                    resume_json    = excluded.resume_json,
                    application_id = excluded.application_id,
                    updated_at     = excluded.updated_at
            """),
            {"uid": user_id, "jid": jid, "aid": application_id,
             "resume_json": resume_json, "now": now},
        )
        await db.commit()
        results[jid] = True
        logger.info("resume_generator: job_id=%d done", jid)

    return results
