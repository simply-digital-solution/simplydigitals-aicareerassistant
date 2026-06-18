"""
Job Application Drafts Agent — Phase 0 (single-call).

Writes cover letter, CV tailoring notes, LinkedIn note, and key match points
for a specific application.
Input: profile dict + resume text + target job description.
Output: ApplicationOutput.
"""
from pathlib import Path
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api_client import get_llm_client
from app.shared.schemas import ApplicationOutput, AgentError

PROMPT_FILE = Path(__file__).parents[4] / "prompts" / "application.md"
AGENT_NAME = "application"

JD_MAX_CHARS = 3000


def _load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def _build_user_message(
    profile: dict[str, Any],
    resume_text: str,
    jd_text: str,
    jd_summary: Optional[str] = None,
) -> str:
    target_roles = ", ".join(profile.get("targets", {}).get("roles", ["the target role"]))
    cover_letter_style = profile.get("communication_style", {}).get("cover_letter", "professional, concise")
    name = profile.get("personal", {}).get("name", "the candidate")

    jd_section = jd_summary if jd_summary else jd_text[:JD_MAX_CHARS]

    return (
        f"Candidate name: {name}\n"
        f"Target roles: {target_roles}\n"
        f"Cover letter style preference: {cover_letter_style}\n\n"
        f"--- CANDIDATE RESUME ---\n{resume_text}\n--- END RESUME ---\n\n"
        f"--- TARGET JOB DESCRIPTION ---\n{jd_section}\n--- END JD ---\n\n"
        f"Write a tailored cover letter and application materials. Return JSON only."
    )


async def run_application_agent(
    profile: dict[str, Any],
    resume_text: str,
    jd_text: str,
    db: Optional[AsyncSession] = None,
    user_id: Optional[int] = None,
    application_id: Optional[int] = None,
    jd_summary: Optional[str] = None,
    stream_callback: Optional[callable] = None,
) -> tuple[ApplicationOutput | AgentError, dict]:
    """
    Run the application drafts agent.

    Returns (ApplicationOutput | AgentError, run_metadata).
    """
    client = get_llm_client()
    system_prompt = _load_system_prompt()
    user_message = _build_user_message(profile, resume_text, jd_text, jd_summary)

    return await client.run_agent(
        agent_name=AGENT_NAME,
        system_prompt=system_prompt,
        user_message=user_message,
        output_schema=ApplicationOutput,
        db=db,
        application_id=application_id,
        user_id=user_id,
        stream_callback=stream_callback,
    )
