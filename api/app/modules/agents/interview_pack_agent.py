"""
Interview Pack Agent — single LLM call.

Generates a 2-minute pitch + 10 STAR questions for a specific job posting.
Persists the result in interview_packs table (upsert by application_id).
"""
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api_client import get_llm_client
from app.shared.schemas import InterviewPackOutput, AgentError

PROMPT_FILE = Path(__file__).parents[4] / "prompts" / "interview_pack.md"
AGENT_NAME = "interview_pack"
JD_MAX_CHARS = 3000


def _load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def _build_user_message(
    profile: dict[str, Any],
    jd_text: str,
    company_name: str,
    jd_summary: Optional[str],
    tailored_resume_text: str = "",
) -> str:
    background = profile.get("background", {})
    targets = profile.get("targets", {})
    jd_section = jd_summary if jd_summary else jd_text[:JD_MAX_CHARS]

    profile_block = (
        f"Candidate background:\n"
        f"- Current title: {background.get('current_title', 'unknown')}\n"
        f"- Years experience: {background.get('years_experience', 'unknown')}\n"
        f"- Target roles: {', '.join(targets.get('roles', []))}\n"
        f"- Key skills: {', '.join(background.get('skills', []))}\n"
        f"- Education: {background.get('education', '')}\n"
        f"- Experience summary: {background.get('experience_summary', '')}\n"
    )
    company_line = f"Target company: {company_name}\n" if company_name else ""

    resume_block = (
        f"--- TAILORED RESUME SENT TO THIS EMPLOYER ---\n{tailored_resume_text}\n--- END RESUME ---\n\n"
        if tailored_resume_text.strip()
        else ""
    )

    return (
        f"{profile_block}\n"
        f"{company_line}"
        f"{resume_block}"
        f"--- TARGET JOB DESCRIPTION ---\n{jd_section}\n--- END JD ---\n\n"
        f"Generate the interview prep pack for this role. Return JSON only."
    )


async def run_interview_pack_agent(
    profile: dict[str, Any],
    jd_text: str,
    db: AsyncSession,
    user_id: int,
    application_id: int,
    company_name: str = "",
    jd_summary: Optional[str] = None,
    tailored_resume_text: str = "",
) -> tuple[InterviewPackOutput | AgentError, dict]:
    client = get_llm_client()
    system_prompt = _load_system_prompt()
    user_message = _build_user_message(profile, jd_text, company_name, jd_summary, tailored_resume_text)

    result, meta = await client.run_agent(
        agent_name=AGENT_NAME,
        system_prompt=system_prompt,
        user_message=user_message,
        output_schema=InterviewPackOutput,
        db=db,
        application_id=application_id,
        user_id=user_id,
    )

    if isinstance(result, InterviewPackOutput):
        import json
        await db.execute(
            text("""
                INSERT INTO interview_packs (user_id, application_id, pitch, star_questions, created_at, updated_at)
                VALUES (:uid, :app_id, :pitch, :star_q, now(), now())
                ON CONFLICT (application_id) DO UPDATE
                SET pitch = EXCLUDED.pitch,
                    star_questions = EXCLUDED.star_questions,
                    updated_at = now()
            """),
            {
                "uid": user_id,
                "app_id": application_id,
                "pitch": result.pitch,
                "star_q": json.dumps([q.model_dump() for q in result.star_questions]),
            },
        )
        await db.commit()

    return result, meta
