"""
Daily industry refinement.

For each active user, aligns their profile's target_industries to the vocabulary
actually used in their job postings. This corrects drift that occurs when:
  - The user's first resume analysis happened before any jobs were scraped
    (free-form labels, no job postings to align to)
  - New job postings introduced industry labels not previously seen

The LLM is given the profile's current industries and the distinct labels from
the user's job postings, and asked to return an aligned list using job-posting
vocabulary. The result replaces target_industries in the profile.

Runs daily after the scrape so new job labels are already present.
"""
import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api_client import get_llm_client

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an industry label alignment assistant.
You will receive two lists:
1. A user's current profile industries (may use informal or short-form labels)
2. The distinct industry labels used in the user's job postings (authoritative vocabulary)

Return ONLY a valid JSON object with one key "industries" containing an array of strings.
Map each profile industry to the closest matching job-posting label.
Rules:
- Only return labels that appear in the job-posting list
- If a profile industry has no close match in the job-posting list, drop it
- Do not add industries that are not in the job-posting list
- Do not invent new labels
- Return empty array if nothing matches
Example: {"industries": ["Banking & Financial Services", "Technology & Software"]}"""


async def refine_user_industries(user_id: int, db: AsyncSession) -> bool:
    """
    Align target_industries for one user to their job-posting vocabulary.
    Returns True if the profile was updated, False otherwise.
    """
    row = await db.execute(
        text("SELECT target_industries FROM profiles WHERE user_id = :uid"),
        {"uid": user_id},
    )
    profile_row = row.fetchone()
    if not profile_row:
        return False

    current_industries: list[str] = json.loads(profile_row[0]) if profile_row[0] else []
    if not current_industries:
        logger.info("industry_refinement: user_id=%d — no profile industries, skipping", user_id)
        return False

    rows = await db.execute(text("""
        SELECT DISTINCT value
        FROM user_job_postings ujp
        JOIN job_postings jp ON jp.id = ujp.job_posting_id,
             json_array_elements_text(jp.inferred_industries::json) AS value
        WHERE ujp.user_id = :uid
          AND jp.inferred_industries IS NOT NULL
          AND jp.inferred_industries != '[]'
        ORDER BY value
    """), {"uid": user_id})
    job_labels: list[str] = [r[0] for r in rows.fetchall()]

    if not job_labels:
        logger.info("industry_refinement: user_id=%d — no job labels yet, skipping", user_id)
        return False

    # Already aligned — every profile industry is already in job labels
    if all(ind in job_labels for ind in current_industries):
        logger.info("industry_refinement: user_id=%d — already aligned, no update needed", user_id)
        return False

    client = get_llm_client()
    user_message = (
        f"Profile industries: {json.dumps(current_industries)}\n"
        f"Job posting labels: {json.dumps(job_labels)}\n"
        f"Return aligned industries as JSON."
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    try:
        raw, _ = await client._call(messages)
    except Exception as exc:
        logger.error("industry_refinement: user_id=%d — LLM call failed: %s", user_id, exc)
        return False

    import re
    text_clean = re.sub(r"```(?:json)?", "", raw).strip()
    match = re.search(r'\{.*\}', text_clean, re.DOTALL)
    if not match:
        logger.warning("industry_refinement: user_id=%d — could not parse LLM response", user_id)
        return False
    try:
        data = json.loads(match.group())
        aligned: list[str] = [str(v).strip() for v in data.get("industries", []) if str(v).strip() in job_labels]
    except (json.JSONDecodeError, TypeError):
        logger.warning("industry_refinement: user_id=%d — JSON decode failed", user_id)
        return False

    if aligned == current_industries:
        logger.info("industry_refinement: user_id=%d — no change after alignment", user_id)
        return False

    await db.execute(
        text("UPDATE profiles SET target_industries = :ind WHERE user_id = :uid"),
        {"ind": json.dumps(aligned), "uid": user_id},
    )
    await db.commit()
    logger.info(
        "industry_refinement: user_id=%d — updated %s → %s",
        user_id, current_industries, aligned,
    )
    return True


async def refine_all_users(get_db_context) -> None:
    """Called by the scheduler — refines industries for every active user."""
    async with get_db_context() as db:
        rows = await db.execute(text("""
            SELECT p.user_id FROM profiles p
            JOIN users u ON u.id = p.user_id
            WHERE u.scoring_suspended = false
        """))
        user_ids = [r[0] for r in rows.fetchall()]

    logger.info("industry_refinement: starting — %d users", len(user_ids))
    updated = 0
    for uid in user_ids:
        try:
            async with get_db_context() as db:
                if await refine_user_industries(uid, db):
                    updated += 1
        except Exception as exc:
            logger.error("industry_refinement: user_id=%d failed: %s", uid, exc, exc_info=True)

    logger.info("industry_refinement: done — %d/%d users updated", updated, len(user_ids))
