"""
Research Agent — Phase 0 (single-call).

Scores and ranks job opportunities against the user's profile.
Input: profile dict + list of job postings (from scraper or manual paste).
Output: ResearchOutput (ranked opportunities with fit scores).
"""
from pathlib import Path
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api_client import get_claude_client
from app.shared.schemas import ResearchOutput, AgentError

PROMPT_FILE = Path(__file__).parents[4] / "prompts" / "research.md"
AGENT_NAME = "research"


def _load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


MAX_JOBS_TO_SCORE = 10   # MCF structured fields are ~100 tokens/job — 10 fits within 4096 output limit
DESC_SNIPPET_CHARS = 300  # fallback for non-MCF sources that return prose descriptions


def _build_user_message(
    profile: dict[str, Any],
    job_postings: list[dict],
    search_filters: dict[str, Any],
    feedback_examples: str = "",
    full_description: bool = False,
) -> str:
    excluded = search_filters.get("excluded_companies") or profile.get('rules', {}).get('excluded_companies', [])
    salary_floor = search_filters.get("salary_floor") or profile.get('compensation', {}).get('min_base', 'N/A')
    salary_currency = search_filters.get("salary_currency") or profile.get('compensation', {}).get('currency', '')
    remote_pref = search_filters.get("remote_preference") or "any"
    employment_type = search_filters.get("employment_type") or "any"
    location = search_filters.get("location") or ', '.join(profile.get('targets', {}).get('locations', []))

    # Trim to avoid exceeding local LLM output token budget
    postings = job_postings[:MAX_JOBS_TO_SCORE]

    candidate_summary = profile.get('candidate_summary') or ''
    seniority = profile.get('seniority_level') or ''
    core_skills = profile.get('core_skills') or profile.get('background', {}).get('skills', [])

    lines = ["Candidate profile:"]
    if candidate_summary:
        lines.append(f"- Summary: {candidate_summary}")
    if seniority:
        lines.append(f"- Seniority: {seniority}")
    lines.append(f"- Years experience: {profile.get('background', {}).get('years_experience', 'unknown')}")
    lines.append(f"- Core skills: {', '.join(core_skills) if core_skills else 'none specified'}")
    lines.append(f"- Location: {location}")
    lines.append(f"- Remote preference: {remote_pref}")
    lines.append(f"- Employment type: {employment_type}")
    lines.append(f"- Min compensation: {salary_floor} {salary_currency}")
    lines.append(f"- Excluded companies: {', '.join(excluded) if excluded else 'none'}")
    profile_block = "\n".join(lines)

    postings_block = f"Job postings to analyze ({len(postings)} total):\n"
    for i, job in enumerate(postings, 1):
        inferred = job.get("inferred_industries") or []
        industry_line = f"Industry: {', '.join(inferred)}\n" if inferred else ""
        desc = str(job.get('description', ''))
        desc_text = desc if full_description else desc[:DESC_SNIPPET_CHARS]
        desc_label = "Description" if full_description else "Snippet"
        postings_block += (
            f"\n[{i}] {job.get('title', 'Unknown')} at {job.get('company', 'Unknown')}\n"
            f"URL: {job.get('url', '')}\n"
            f"{industry_line}"
            f"{desc_label}: {desc_text}\n"
        )

    feedback_block = f"\n{feedback_examples}\n" if feedback_examples else ""

    return (
        f"{profile_block}\n"
        f"{feedback_block}"
        f"{postings_block}\n\n"
        f"Return a JSON object with an \"opportunities\" array containing exactly {len(postings)} items, "
        f"one per posting above. Do not omit any posting."
    )


async def run_research_agent(
    profile: dict[str, Any],
    job_postings: list[dict],
    search_filters: dict[str, Any] | None = None,
    db: Optional[AsyncSession] = None,
    user_id: Optional[int] = None,
    application_id: Optional[int] = None,
    stream_callback: Optional[callable] = None,
    feedback_examples: str = "",
    full_description: bool = False,
) -> tuple[ResearchOutput | AgentError, dict]:
    """
    Run the research agent against a list of job postings.

    Returns (ResearchOutput | AgentError, run_metadata).
    """
    client = get_claude_client()
    system_prompt = _load_system_prompt()
    user_message = _build_user_message(
        profile, job_postings, search_filters or {}, feedback_examples, full_description
    )

    return await client.run_agent(
        agent_name=AGENT_NAME,
        system_prompt=system_prompt,
        user_message=user_message,
        output_schema=ResearchOutput,
        db=db,
        application_id=application_id,
        user_id=user_id,
        stream_callback=stream_callback,
    )
