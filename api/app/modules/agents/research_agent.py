"""
Research Agent — Phase 0 (single-call).

Scores and ranks job opportunities against the user's profile.
Input: profile dict + list of job postings (from scraper or manual paste).
Output: ResearchOutput (ranked opportunities with fit scores).
"""
from pathlib import Path
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api_client import get_llm_client, get_scorer_client
from app.shared.schemas import ResearchOutput, AgentError

PROMPT_FILE = Path(__file__).parents[3] / "prompts" / "research.md"
AGENT_NAME = "research"


def _load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


DESC_SNIPPET_CHARS = 300  # fallback for non-MCF sources that return prose descriptions


def _build_user_message(
    profile: dict[str, Any],
    job_postings: list[dict],
    search_filters: dict[str, Any],
    feedback_examples: str = "",
    full_description: bool = False,
) -> str:
    cacheable_prefix, variable_suffix = _build_user_message_parts(
        profile, job_postings, search_filters, feedback_examples, full_description
    )
    return f"{cacheable_prefix}{variable_suffix}"


def _build_user_message_parts(
    profile: dict[str, Any],
    job_postings: list[dict],
    search_filters: dict[str, Any],
    feedback_examples: str = "",
    full_description: bool = False,
) -> tuple[str, str]:
    """
    Same content as _build_user_message(), split into two pieces at the
    boundary between what's identical across every job scored for this user
    (profile + resume) and what varies per call (the job postings). Callers
    that want prompt caching send the two pieces separately with a cache
    marker on the first; _build_user_message() just concatenates them for
    callers that don't care about caching.
    """
    excluded = search_filters.get("excluded_companies") or profile.get('rules', {}).get('excluded_companies', [])
    salary_floor = search_filters.get("salary_floor") or profile.get('compensation', {}).get('min_base', 'N/A')
    salary_currency = search_filters.get("salary_currency") or profile.get('compensation', {}).get('currency', '')
    remote_pref = search_filters.get("remote_preference") or "any"
    employment_type = search_filters.get("employment_type") or "any"
    location = search_filters.get("location") or ', '.join(profile.get('targets', {}).get('locations', []))

    postings = job_postings

    candidate_summary = profile.get('candidate_summary') or ''
    seniority = profile.get('seniority_level') or ''
    core_skills = profile.get('core_skills') or profile.get('background', {}).get('skills', [])
    resume_text = (profile.get('resume_text') or '').strip()

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

    resume_block = f"\nFull resume (use this as the primary source of truth for the candidate's actual experience):\n{resume_text}\n" if resume_text else ""

    # Everything above this point is identical across every job scored for
    # this user in the same batch — the cacheable prefix.
    cacheable_prefix = f"{profile_block}\n{resume_block}"

    postings_block = f"Job postings to analyze ({len(postings)} total):\n"
    for i, job in enumerate(postings, 1):
        inferred = job.get("inferred_industries") or []
        industry_line = f"Industry: {', '.join(inferred)}\n" if inferred else ""
        desc = str(job.get('description', ''))
        desc_text = desc if full_description else desc[:DESC_SNIPPET_CHARS]
        desc_label = "Description" if full_description else "Snippet"
        job_id_line = f"job_id: {job['job_id']}\n" if job.get('job_id') else ""
        postings_block += (
            f"\n[{i}] {job.get('title', 'Unknown')} at {job.get('company', 'Unknown')}\n"
            f"{job_id_line}"
            f"URL: {job.get('url', '')}\n"
            f"{industry_line}"
            f"{desc_label}: {desc_text}\n"
        )

    feedback_block = f"\n{feedback_examples}\n" if feedback_examples else ""

    variable_suffix = (
        f"{feedback_block}"
        f"{postings_block}\n\n"
        f"Return a JSON object with an \"opportunities\" array containing exactly {len(postings)} items, "
        f"one per posting above. Do not omit any posting."
    )

    return cacheable_prefix, variable_suffix


async def run_research_agent(
    profile: dict[str, Any],
    job_postings: list[dict],
    search_filters: dict[str, Any] | None = None,
    db: Optional[AsyncSession] = None,
    user_id: Optional[int] = None,
    application_id: Optional[int] = None,
    job_posting_id: Optional[int] = None,
    request_type: str = "research",
    stream_callback: Optional[callable] = None,
    feedback_examples: str = "",
    full_description: bool = False,
    max_self_corrections: Optional[int] = None,
) -> tuple[ResearchOutput | AgentError, dict]:
    """
    Run the research agent against a list of job postings.

    Returns (ResearchOutput | AgentError, run_metadata).
    """
    # Scoring (request_type="scoring", the llm_scorer.py path) uses its own
    # client so it can run on a different model than the rest of the
    # research agent (e.g. the chat/search research flow, request_type
    # default "research") without affecting it.
    client = get_scorer_client() if request_type == "scoring" else get_llm_client()
    system_prompt = _load_system_prompt()
    cacheable_prefix, variable_suffix = _build_user_message_parts(
        profile, job_postings, search_filters or {}, feedback_examples, full_description
    )

    # Scoring jobs sequentially within a batch sends the same profile+resume
    # prefix on every call — mark it cacheable so only the first call in a
    # ~5-minute window pays full price for it. Other request types (chat
    # research, etc.) don't batch the same way, so they skip the split and
    # send everything as one plain message, same as before.
    if request_type == "scoring":
        user_message = variable_suffix
        cache_kwargs = {"cacheable_prefix": cacheable_prefix}
    else:
        user_message = f"{cacheable_prefix}{variable_suffix}"
        cache_kwargs = {}

    return await client.run_agent(
        agent_name=AGENT_NAME,
        system_prompt=system_prompt,
        user_message=user_message,
        output_schema=ResearchOutput,
        db=db,
        application_id=application_id,
        user_id=user_id,
        job_posting_id=job_posting_id,
        request_type=request_type,
        stream_callback=stream_callback,
        max_self_corrections=max_self_corrections,
        **cache_kwargs,
    )
