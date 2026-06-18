"""
Interview Coach Agent — Phase 0 (single-call).

Generates behavioural, technical, and STAR prep for a specific role.
Input: profile dict + target job description.
Output: InterviewOutput.
"""
from pathlib import Path
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api_client import get_llm_client
from app.shared.schemas import InterviewOutput, AgentError

PROMPT_FILE = Path(__file__).parents[4] / "prompts" / "interview.md"
AGENT_NAME = "interview"

JD_MAX_CHARS = 3000


def _load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def _build_user_message(
    profile: dict[str, Any],
    jd_text: str,
    company_name: str = "",
    jd_summary: Optional[str] = None,
) -> str:
    background = profile.get("background", {})
    targets = profile.get("targets", {})

    jd_section = jd_summary if jd_summary else jd_text[:JD_MAX_CHARS]

    profile_block = (
        f"Candidate background:\n"
        f"- Current title: {background.get('current_title', 'unknown')}\n"
        f"- Years experience: {background.get('years_experience', 'unknown')}\n"
        f"- Target roles: {', '.join(targets.get('roles', []))}\n"
        f"- Target seniority: {targets.get('seniority', 'senior')}\n"
        f"- Key skills: {', '.join(background.get('skills', []))}\n"
        f"- Education: {background.get('education', '')}\n"
        f"- Experience summary: {background.get('experience_summary', '')}\n"
    )

    company_line = f"Target company: {company_name}\n" if company_name else ""

    return (
        f"{profile_block}\n"
        f"{company_line}"
        f"--- TARGET JOB DESCRIPTION ---\n{jd_section}\n--- END JD ---\n\n"
        f"Prepare a comprehensive interview prep pack for this role. Return JSON only."
    )


async def run_interview_agent(
    profile: dict[str, Any],
    jd_text: str,
    db: Optional[AsyncSession] = None,
    user_id: Optional[int] = None,
    application_id: Optional[int] = None,
    company_name: str = "",
    jd_summary: Optional[str] = None,
    stream_callback: Optional[callable] = None,
) -> tuple[InterviewOutput | AgentError, dict]:
    """
    Run the interview coach agent.

    Returns (InterviewOutput | AgentError, run_metadata).
    """
    client = get_llm_client()
    system_prompt = _load_system_prompt()
    user_message = _build_user_message(profile, jd_text, company_name, jd_summary)

    return await client.run_agent(
        agent_name=AGENT_NAME,
        system_prompt=system_prompt,
        user_message=user_message,
        output_schema=InterviewOutput,
        db=db,
        application_id=application_id,
        user_id=user_id,
        stream_callback=stream_callback,
    )
