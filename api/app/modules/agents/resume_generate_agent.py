"""
Resume Generator Agent.

Takes the candidate's original resume text + job description and produces
a complete tailored resume in the candidate's own format and style.
"""
from pathlib import Path
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api_client import get_claude_client
from app.shared.schemas import GeneratedResumeOutput, AgentError

PROMPT_FILE = Path(__file__).parents[4] / "prompts" / "resume_generate.md"
AGENT_NAME  = "resume_generate"

JD_MAX_CHARS = 4000


def _load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def _build_user_message(
    resume_text: str,
    jd_text: str,
    candidate_name: str = "",
) -> str:
    jd_section = jd_text[:JD_MAX_CHARS]
    name_line  = f"Candidate name: {candidate_name}\n\n" if candidate_name else ""

    return (
        f"{name_line}"
        f"--- CANDIDATE'S ORIGINAL RESUME ---\n{resume_text}\n"
        f"--- END RESUME ---\n\n"
        f"--- TARGET JOB DESCRIPTION ---\n{jd_section}\n"
        f"--- END JOB DESCRIPTION ---\n\n"
        "Produce a complete tailored resume following the candidate's exact "
        "section structure and style. Return JSON only."
    )


async def run_resume_generate_agent(
    resume_text: str,
    jd_text: str,
    candidate_name: str = "",
    db: Optional[AsyncSession] = None,
    user_id: Optional[int] = None,
    application_id: Optional[int] = None,
) -> tuple[GeneratedResumeOutput | AgentError, dict]:
    """
    Generate a tailored resume for a specific job.

    Returns (GeneratedResumeOutput | AgentError, run_metadata).
    """
    client         = get_claude_client()
    system_prompt  = _load_system_prompt()
    user_message   = _build_user_message(resume_text, jd_text, candidate_name)

    return await client.run_agent(
        agent_name=AGENT_NAME,
        system_prompt=system_prompt,
        user_message=user_message,
        output_schema=GeneratedResumeOutput,
        db=db,
        application_id=application_id,
        user_id=user_id,
    )
