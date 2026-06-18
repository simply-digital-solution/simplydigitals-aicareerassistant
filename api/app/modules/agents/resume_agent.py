"""
Resume & LinkedIn Optimizer Agent — Phase 0 (single-call).

Tailors a candidate's resume and LinkedIn profile for a specific role.
Input: profile dict + resume text + target job description.
Output: ResumeOutput (line edits, headline, about options, skills).
"""
from pathlib import Path
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api_client import get_llm_client
from app.shared.schemas import ResumeOutput, AgentError

PROMPT_FILE = Path(__file__).parents[4] / "prompts" / "resume.md"
AGENT_NAME = "resume"

# JD truncation limit — prevents flooding context window
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

    # Use memoized summary if available; otherwise truncate raw JD
    jd_section = jd_summary if jd_summary else jd_text[:JD_MAX_CHARS]

    return (
        f"Target roles: {target_roles}\n\n"
        f"Communication preferences: "
        f"{profile.get('communication_style', {}).get('cover_letter', 'professional')}\n\n"
        f"--- CANDIDATE RESUME ---\n{resume_text}\n--- END RESUME ---\n\n"
        f"--- TARGET JOB DESCRIPTION ---\n{jd_section}\n--- END JD ---\n\n"
        f"Produce tailored resume improvements and LinkedIn profile updates. Return JSON only."
    )


async def run_resume_agent(
    profile: dict[str, Any],
    resume_text: str,
    jd_text: str,
    db: Optional[AsyncSession] = None,
    user_id: Optional[int] = None,
    application_id: Optional[int] = None,
    jd_summary: Optional[str] = None,
    stream_callback: Optional[callable] = None,
) -> tuple[ResumeOutput | AgentError, dict]:
    """
    Run the resume optimizer agent.

    Returns (ResumeOutput | AgentError, run_metadata).
    """
    client = get_llm_client()
    system_prompt = _load_system_prompt()
    user_message = _build_user_message(profile, resume_text, jd_text, jd_summary)

    return await client.run_agent(
        agent_name=AGENT_NAME,
        system_prompt=system_prompt,
        user_message=user_message,
        output_schema=ResumeOutput,
        db=db,
        application_id=application_id,
        user_id=user_id,
        stream_callback=stream_callback,
    )
