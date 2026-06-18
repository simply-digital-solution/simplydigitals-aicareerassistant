"""
Industry backfill tool.

Finds all job_postings with inferred_industries = '[]' and classifies them
using Gemini — updating only inferred_industries, leaving scores untouched.

Usage:
    cd api && poetry run python -m app.pipeline.industry_backfill
"""
import asyncio
import json
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api_client import get_llm_client
from app.shared.schemas import IndustryClassifierOutput, AgentError

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parents[3] / "prompts" / "industry_classifier.md"
BATCH_SIZE = 30
DESC_SNIPPET_CHARS = 300


def _load_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def _build_user_message(jobs: list[dict]) -> str:
    lines = [f"Classify the following {len(jobs)} job postings into industries:\n"]
    for job in jobs:
        desc = (job.get("description") or "")[:DESC_SNIPPET_CHARS]
        lines.append(
            f"job_id: {job['id']}\n"
            f"Title: {job['title']}\n"
            f"Company: {job['company']}\n"
            f"Description: {desc}\n"
        )
    lines.append(
        f"\nReturn a JSON object with a \"classifications\" array containing exactly "
        f"{len(jobs)} items, one per posting. Echo the exact job_id for each."
    )
    return "\n".join(lines)


async def backfill_industries(db: AsyncSession) -> int:
    """
    Classify all jobs with inferred_industries = '[]'.
    Returns the number of jobs successfully classified.
    """
    rows = await db.execute(
        text("""
            SELECT id, title, company, description
            FROM job_postings
            WHERE inferred_industries = '[]' OR inferred_industries IS NULL
            ORDER BY id ASC
        """)
    )
    jobs = rows.mappings().all()

    if not jobs:
        logger.info("industry_backfill: no jobs to classify")
        return 0

    logger.info("industry_backfill: %d jobs to classify", len(jobs))
    client = get_llm_client()
    system_prompt = _load_prompt()
    total_classified = 0

    for batch_start in range(0, len(jobs), BATCH_SIZE):
        batch = jobs[batch_start: batch_start + BATCH_SIZE]
        job_ids = [j["id"] for j in batch]
        logger.info(
            "industry_backfill: batch %d-%d (%d jobs)",
            batch_start + 1, batch_start + len(batch), len(batch),
        )

        user_message = _build_user_message(batch)
        try:
            result, _ = await client.run_agent(
                agent_name="industry_classifier",
                system_prompt=system_prompt,
                user_message=user_message,
                output_schema=IndustryClassifierOutput,
                request_type="industry_backfill",
            )
        except Exception as exc:
            logger.error("industry_backfill: batch %s failed: %s", job_ids, exc)
            continue

        if isinstance(result, AgentError):
            logger.warning("industry_backfill: batch %s agent error: %s", job_ids, result.error)
            continue

        classified = {c.job_id: c.industries for c in result.classifications}
        for job in batch:
            jid = job["id"]
            industries = classified.get(jid)
            if industries is None:
                logger.warning("industry_backfill: job_id=%d missing from response", jid)
                continue
            await db.execute(
                text("UPDATE job_postings SET inferred_industries = :ind WHERE id = :id"),
                {"ind": json.dumps(industries), "id": jid},
            )
            logger.info("industry_backfill: job_id=%d → %s", jid, industries)
            total_classified += 1

        await db.commit()

    logger.info("industry_backfill: done — %d/%d classified", total_classified, len(jobs))
    return total_classified


async def _main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from app.shared.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        classified = await backfill_industries(db)
    print(f"Classified {classified} jobs.")


if __name__ == "__main__":
    asyncio.run(_main())
