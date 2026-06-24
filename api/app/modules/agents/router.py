"""
Agent API endpoints — Phase 0.

Endpoints:
  POST /api/v1/agents/research          — run research agent (SSE stream)
  POST /api/v1/agents/resume            — run resume agent (SSE stream)
  POST /api/v1/agents/application       — run application drafts agent (SSE stream)
  POST /api/v1/agents/interview         — run interview coach agent (SSE stream)
  POST /api/v1/agents/run               — trigger full LangGraph session
  GET  /api/v1/agents/sessions/{id}     — session status
  GET  /api/v1/agents/runs/{id}         — single agent run detail
  GET  /api/v1/research/jobs/interviewing — jobs with status interviewing/offered/rejected
  POST /api/v1/agents/interview-from-job  — generate & save interview pack for an application
  GET  /api/v1/agents/interview-pack/{application_id} — fetch cached interview pack

  GET  /api/v1/approvals/pending        — drafts awaiting review
  POST /api/v1/approvals/{id}/approve   — approve a draft
  POST /api/v1/approvals/{id}/edit      — approve with edits
  POST /api/v1/approvals/{id}/reject    — reject a draft

  GET  /api/v1/budget/summary           — daily cost breakdown
  GET  /api/v1/audit/log                — recent audit events
  GET  /api/v1/audit/verify             — verify hash-chain integrity
"""
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Any
from app.shared.sql_compat import now_utc

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import StreamingResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.shared.database import get_db
from app.shared.config import get_settings
from app.modules.auth.router import get_current_user
from app.modules.agents.research_agent import run_research_agent
from app.modules.agents.resume_agent import run_resume_agent
from app.modules.agents.application_agent import run_application_agent
from app.modules.agents.interview_agent import run_interview_agent
from app.modules.agents.interview_pack_agent import run_interview_pack_agent
from app.pipeline.graph import run_session
from app.shared.schemas import AgentError

router = APIRouter(prefix="/api/v1", tags=["agents"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ResearchRequest(BaseModel):
    # All optional — if empty, scraper fetches jobs automatically from profile targets
    job_postings: list[dict] = Field(default_factory=list)
    query: Optional[str] = None
    queries: list[str] = Field(default_factory=list)   # multiple roles — scrape all in parallel
    location: Optional[str] = None
    remote_preference: Optional[str] = None
    employment_type: Optional[str] = None
    salary_floor: Optional[int] = None
    salary_currency: Optional[str] = None
    required_skills: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    application_id: Optional[int] = None


class ResumeRequest(BaseModel):
    jd_text: str
    resume_text: Optional[str] = None  # if omitted, loaded from DB profile
    jd_summary: Optional[str] = None
    application_id: Optional[int] = None


class ApplicationRequest(BaseModel):
    jd_text: str
    resume_text: Optional[str] = None  # if omitted, loaded from DB profile
    jd_summary: Optional[str] = None
    application_id: Optional[int] = None


class InterviewRequest(BaseModel):
    jd_text: str
    company_name: str = ""
    jd_summary: Optional[str] = None
    application_id: Optional[int] = None


class InterviewFromJobRequest(BaseModel):
    application_id: int


class RunSessionRequest(BaseModel):
    job_postings: Optional[list[dict]] = None
    job_description: Optional[str] = None
    trigger: str = "manual"


class ApprovalEditRequest(BaseModel):
    edited_content: str


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse(event: str, data: Any) -> str:
    """Format one SSE frame."""
    payload = json.dumps(data) if not isinstance(data, str) else data
    return f"event: {event}\ndata: {payload}\n\n"


def _industry_match(a: str, b: str) -> float:
    """
    Return similarity between two industry strings (case-insensitive).

    Three-level check (returns highest):
    1. Substring — "Banking & Finance" in "Banking & Financial Services" → 1.0
    2. Segment — split by "&", best pairwise SequenceMatcher ratio across segments
       catches "Banking & Finance" vs "Banking & Financial Services" (finance≈financial)
    3. Full string SequenceMatcher fallback
    """
    from difflib import SequenceMatcher
    a_l, b_l = a.lower(), b.lower()
    if a_l in b_l or b_l in a_l:
        return 1.0
    segs_a = [s.strip() for s in a_l.split("&")]
    segs_b = [s.strip() for s in b_l.split("&")]
    seg_score = max(
        (SequenceMatcher(None, sa, sb).ratio() for sa in segs_a for sb in segs_b),
        default=0.0,
    )
    return max(SequenceMatcher(None, a_l, b_l).ratio(), seg_score)


def _filter_by_industry(
    jobs: list[dict],
    target_industries: list[str],
    threshold: float = 0.80,
) -> list[dict]:
    """
    Keep a job if:
      - target_industries is empty (no filter configured), OR
      - it has no inferred industries (can't exclude what we don't know), OR
      - at least one inferred industry fuzzy-matches at least one target industry
        at >= threshold similarity.
    """
    if not target_industries:
        return jobs
    kept = []
    for job in jobs:
        inferred: list[str] = job.get("inferred_industries") or []
        if not inferred:
            kept.append(job)
            continue
        for inf in inferred:
            if any(_industry_match(inf, tgt) >= threshold for tgt in target_industries):
                kept.append(job)
                break
    return kept


async def _stream_research(
    request: ResearchRequest,
    user_id: int,
    db: AsyncSession,
):
    """Generator: auto-scrapes jobs if none provided, then streams research agent."""
    import time
    import logging
    from app.pipeline.scraper import search_jobs
    _log = logging.getLogger("research_timing")

    t_start = time.monotonic()
    profile = await _load_profile(db, user_id)
    _log.info("TIMING load_profile: %.2fs", time.monotonic() - t_start)
    targets = profile.get("targets", {})

    # Load not-relevant job URLs so we can filter them out after scraping
    nr_rows = await db.execute(
        text("SELECT job_url FROM job_feedback WHERE user_id = :uid AND relevance = 'not_relevant'"),
        {"uid": user_id},
    )
    not_relevant_urls: set[str] = {r[0] for r in nr_rows.fetchall()}

    job_postings = list(request.job_postings)

    # Auto-scrape when caller provides no postings
    if not job_postings:
        location = request.location or (targets.get("locations") or ["Remote"])[0]

        # Build list of roles to search — use queries[] if provided, else single query, else target_titles
        if request.queries:
            roles_to_search = request.queries
        elif request.query:
            roles_to_search = [request.query]
        else:
            roles_to_search = profile.get("target_titles") or targets.get("roles") or [""]

        # skill_keywords from request override profile; otherwise use top core_skills
        core_skills: list[str] = profile.get("core_skills") or []
        industries: list[str] = profile.get("industries") or []
        explicit_skills: list[str] = request.required_skills or []

        # Use top industry as a domain keyword to sharpen the query
        _INDUSTRY_SHORT = {
            "Banking & Financial Services": "banking",
            "Capital Markets & Investment Management": "investment management",
            "Technology & Software": "technology",
            "Consulting & Professional Services": "consulting",
            "Government & Public Sector": "government",
            "Healthcare & Life Sciences": "healthcare",
            "Real Estate & Infrastructure": "real estate",
            "Supply Chain & Logistics": "logistics",
            "Media, Marketing & Communications": "marketing",
            "Insurance": "insurance",
            "Energy & Resources": "energy",
            "Education": "education",
        }
        industry_keyword = _INDUSTRY_SHORT.get(industries[0], "") if industries else ""

        yield _sse("status", {"message": f"Searching {len(roles_to_search)} role(s) in {location}…"})

        # Fan out — scrape all roles in parallel
        scrape_errors: list[str] = []

        async def scrape_role(role: str) -> list[dict]:
            # Build query: "Product Owner banking Python SQL"
            if explicit_skills:
                skills_for_role = explicit_skills[:3]
            else:
                skills_for_role = core_skills[:3]

            skill_suffix = " ".join(skills_for_role)
            # Role title is now the full target title — no seniority prefix needed
            q = f"{role} {industry_keyword} {skill_suffix}".strip()
            q = " ".join(q.split())  # collapse multiple spaces
            t0 = time.monotonic()
            try:
                jobs = await search_jobs(query=q, location=location, max_per_source=10, keyword_filter=role)
                _log.info("TIMING scrape %r: %.2fs → %d jobs", role, time.monotonic() - t0, len(jobs))
                return jobs
            except Exception as exc:
                _log.warning("TIMING scrape %r: %.2fs → ERROR: %s", role, time.monotonic() - t0, exc)
                scrape_errors.append(f"{role}: {exc}")
                return []

        t_scrape = time.monotonic()
        results = await asyncio.gather(*[scrape_role(r) for r in roles_to_search])
        _log.info("TIMING scrape total (parallel): %.2fs", time.monotonic() - t_scrape)

        # Flatten, deduplicate, and remove not-relevant jobs
        seen_urls: set[str] = set()
        for batch in results:
            for job in batch:
                url = job.get("url", "")
                if url and url in seen_urls:
                    continue
                if url and url in not_relevant_urls:
                    continue
                seen_urls.add(url)
                job_postings.append(job)

        # Filter excluded companies
        if request.excluded_companies:
            excluded_lower = {c.lower() for c in request.excluded_companies}
            job_postings = [j for j in job_postings if j.get("company", "").lower() not in excluded_lower]

        # Filter by target industry — keep jobs that match ≥80% OR have no inferred industry
        target_industries: list[str] = profile.get("industries") or []
        if target_industries:
            job_postings = _filter_by_industry(job_postings, target_industries, threshold=0.80)

        if not job_postings:
            if scrape_errors:
                error_summary = "; ".join(scrape_errors[:3])
                yield _sse("error", {"error": f"Job search failed: {error_summary}"})
            else:
                yield _sse("error", {"error": "No jobs found. Try different roles or location."})
            return

        _log.info("TIMING jobs ready: %d total, %.2fs since start", len(job_postings), time.monotonic() - t_start)
        yield _sse("status", {"message": f"Found {len(job_postings)} jobs across {len(roles_to_search)} role(s). Scoring against your profile…"})

    # Merge request-level overrides into profile so research_agent sees them
    search_filters = {
        "location": request.location,
        "remote_preference": request.remote_preference,
        "employment_type": request.employment_type,
        "salary_floor": request.salary_floor,
        "salary_currency": request.salary_currency,
        "required_skills": request.required_skills,
        "excluded_companies": request.excluded_companies,
    }

    queue: asyncio.Queue = asyncio.Queue()

    async def chunk_cb(text: str):
        await queue.put(("chunk", text))

    async def run():
        try:
            result, meta = await run_research_agent(
                profile=profile,
                job_postings=job_postings,
                search_filters=search_filters,
                db=db,
                user_id=user_id,
                application_id=request.application_id,
                stream_callback=chunk_cb,
            )
            await queue.put(("done", (result, meta)))
        except Exception as exc:
            await queue.put(("done", (AgentError(error=f"Research agent error: {exc}"), {})))

    task = asyncio.create_task(run())

    while True:
        item = await queue.get()
        kind, payload = item
        if kind == "chunk":
            yield _sse("chunk", {"text": payload})
        elif kind == "done":
            result, meta = payload
            if isinstance(result, AgentError):
                yield _sse("error", {"error": result.error, "needs_human_review": result.needs_human_review})
            else:
                yield _sse("result", result.model_dump())
                # Background: distill required skills per target title from JD keywords
                target_titles = profile.get("target_titles") or []
                if target_titles and result.opportunities:
                    try:
                        from app.shared.skill_gap import update_title_skills_from_research
                        from app.shared.api_client import get_llm_client
                        client = get_llm_client()
                        opps_as_dicts = [o.model_dump() for o in result.opportunities]
                        asyncio.create_task(
                            update_title_skills_from_research(db, user_id, target_titles, opps_as_dicts, client)
                        )
                    except Exception:
                        pass
            yield _sse("meta", meta)
            break

    await task


async def _stream_resume(
    request: ResumeRequest,
    user_id: int,
    db: AsyncSession,
):
    """Generator: streams resume agent. Loads resume from DB if not provided."""
    profile = await _load_profile(db, user_id)

    resume_text = request.resume_text or await _load_resume_from_db(db, user_id)
    if not resume_text:
        yield _sse("error", {"error": "No resume found. Please upload your resume in the Profile tab first."})
        return

    async for chunk in _stream_agent(
        run_resume_agent,
        {
            "profile": profile,
            "resume_text": resume_text,
            "jd_text": request.jd_text,
            "jd_summary": request.jd_summary,
            "db": db,
            "user_id": user_id,
            "application_id": request.application_id,
        },
    ):
        yield chunk


async def _load_profile(db: AsyncSession | None = None, user_id: int | None = None) -> dict:
    """Load profile from DB as a dict the research agent understands."""
    if db is None or user_id is None:
        return {}
    from sqlalchemy import select
    from app.shared.models import Profile
    import json
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    p = result.scalar_one_or_none()
    if not p:
        return {}
    skills = json.loads(p.skills) if p.skills else []
    target_titles = json.loads(p.target_titles) if p.target_titles else []
    return {
        "targets": {
            "roles": target_titles,
            "locations": json.loads(p.target_locations) if p.target_locations else [],
        },
        "background": {
            "years_experience": p.years_experience,
            "skills": skills,
            "resume_text": p.resume_text or "",
        },
        "compensation": {
            "min_base": p.salary_floor,
            "currency": p.salary_currency or "USD",
        },
        "rules": {
            "excluded_companies": json.loads(p.excluded_companies) if p.excluded_companies else [],
        },
        "preferences": {
            "remote": p.remote_preference or "any",
            "employment_type": p.employment_type or "any",
        },
        "role_key_skills": {},
        "candidate_summary": "",
        "target_titles": target_titles,
        "core_skills": skills,
        "industries": json.loads(p.target_industries) if p.target_industries else [],
        "full_name": p.full_name or "",
        "resume_text": p.resume_text or "",
    }


def _flatten_resume_json(resume_json: str) -> str:
    """Convert stored resume_json into plain text for use in LLM prompts."""
    import json as _json
    try:
        data = _json.loads(resume_json)
    except Exception:
        return ""
    lines: list[str] = []
    if data.get("name"):
        lines.append(data["name"])
    if data.get("headline"):
        lines.append(data["headline"])
    for section in data.get("sections", []):
        lines.append(f"\n{section.get('title', '').upper()}")
        for para in section.get("content", []):
            lines.append(para)
        for exp in section.get("experience", []):
            lines.append(f"{exp.get('title', '')} at {exp.get('company', '')} ({exp.get('dates', '')})")
            if exp.get("summary"):
                lines.append(exp["summary"])
            for bullet in exp.get("bullets", []):
                lines.append(f"• {bullet}")
    return "\n".join(lines)


async def _load_resume_from_db(db: AsyncSession, user_id: int) -> str:
    """Return stored resume text for a user, or empty string if none saved."""
    from sqlalchemy import select
    from app.shared.models import Profile
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    return (profile.resume_text or "") if profile else ""


async def _stream_agent(agent_fn, agent_kwargs: dict):
    """Generic SSE stream wrapper for any agent function."""
    queue: asyncio.Queue = asyncio.Queue()

    async def chunk_cb(text: str):
        await queue.put(("chunk", text))

    agent_kwargs["stream_callback"] = chunk_cb

    async def run():
        try:
            result, meta = await agent_fn(**agent_kwargs)
            await queue.put(("done", (result, meta)))
        except Exception as exc:
            await queue.put(("done", (AgentError(error=f"Agent error: {exc}"), {})))

    task = asyncio.create_task(run())

    while True:
        item = await queue.get()
        kind, payload = item
        if kind == "chunk":
            yield _sse("chunk", {"text": payload})
        elif kind == "done":
            result, meta = payload
            if isinstance(result, AgentError):
                yield _sse("error", {"error": result.error, "needs_human_review": result.needs_human_review})
            else:
                yield _sse("result", result.model_dump())
            yield _sse("meta", meta)
            break

    await task


# ---------------------------------------------------------------------------
# Agent endpoints
# ---------------------------------------------------------------------------

@router.post("/agents/research")
async def research(
    request: ResearchRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream research agent output as SSE."""
    return StreamingResponse(
        _stream_research(request, user_id=current_user.id, db=db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/agents/resume")
async def resume(
    request: ResumeRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream resume agent output as SSE. Resume loaded from DB if not provided."""
    if not request.jd_text:
        raise HTTPException(status_code=422, detail="jd_text is required")

    return StreamingResponse(
        _stream_resume(request, user_id=current_user.id, db=db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/agents/application")
async def application(
    request: ApplicationRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream application drafts agent output as SSE. Resume loaded from DB if not provided."""
    if not request.jd_text:
        raise HTTPException(status_code=422, detail="jd_text is required")

    profile = await _load_profile(db, current_user.id)
    resume_text = request.resume_text or await _load_resume_from_db(db, current_user.id)

    async def _gen():
        if not resume_text:
            yield _sse("error", {"error": "No resume found. Please upload your resume in the Profile tab first."})
            return
        async for chunk in _stream_agent(
            run_application_agent,
            {
                "profile": profile,
                "resume_text": resume_text,
                "jd_text": request.jd_text,
                "jd_summary": request.jd_summary,
                "db": db,
                "user_id": current_user.id,
                "application_id": request.application_id,
            },
        ):
            yield chunk

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/agents/interview")
async def interview(
    request: InterviewRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream interview coach agent output as SSE."""
    if not request.jd_text:
        raise HTTPException(status_code=422, detail="jd_text is required")

    profile = await _load_profile(db, current_user.id)
    return StreamingResponse(
        _stream_agent(
            run_interview_agent,
            {
                "profile": profile,
                "jd_text": request.jd_text,
                "company_name": request.company_name,
                "jd_summary": request.jd_summary,
                "db": db,
                "user_id": current_user.id,
                "application_id": request.application_id,
            },
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/agents/interview-from-job")
async def interview_from_job(
    request: InterviewFromJobRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate (or regenerate) an interview pack for an existing application. Stores result in DB."""
    row = await db.execute(
        text("""
            SELECT a.id, a.job_description, a.jd_summary, jp.company, a.job_posting_id,
                   jp.description AS posting_description
            FROM applications a
            LEFT JOIN job_postings jp ON jp.id = a.job_posting_id
            WHERE a.id = :app_id AND a.user_id = :uid
        """),
        {"app_id": request.application_id, "uid": current_user.id},
    )
    app_row = row.first()
    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found.")

    # Prefer application-level JD (manually entered); fall back to scraped job posting description
    jd_text = app_row[1] or app_row[5] or ""
    jd_summary = app_row[2]
    company_name = app_row[3] or ""
    job_posting_id = app_row[4]

    if not jd_text:
        raise HTTPException(status_code=422, detail="Application has no job description.")

    # Fetch the tailored resume stored for this job posting (if any)
    tailored_resume_text = ""
    if job_posting_id:
        gr_row = await db.execute(
            text("SELECT resume_json FROM generated_resumes WHERE user_id = :uid AND job_posting_id = :jid"),
            {"uid": current_user.id, "jid": job_posting_id},
        )
        gr = gr_row.first()
        if gr and gr[0]:
            tailored_resume_text = _flatten_resume_json(gr[0])

    profile = await _load_profile(db, current_user.id)
    result, _meta = await run_interview_pack_agent(
        profile=profile,
        jd_text=jd_text,
        db=db,
        user_id=current_user.id,
        application_id=request.application_id,
        company_name=company_name,
        jd_summary=jd_summary,
        tailored_resume_text=tailored_resume_text,
    )

    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=500, detail=result.get("message", "Agent failed."))

    from app.shared.schemas import AgentError
    if isinstance(result, AgentError):
        raise HTTPException(status_code=500, detail=result.error)

    # Attempt Drive upload if user has OAuth tokens
    prof_result = await db.execute(
        text("SELECT google_access_token, google_refresh_token, google_token_expiry FROM profiles WHERE user_id = :uid"),
        {"uid": current_user.id},
    )
    prof = prof_result.mappings().first()
    drive_connected = bool(prof and prof["google_refresh_token"])

    if drive_connected:
        from app.shared.interview_pack_docx import build_interview_pack_docx
        from app.shared.google_drive import upload_or_update_file, convert_docx_to_pdf_bytes
        from app.shared.schemas import InterviewPackOutput as _IPO

        job_title = app_row[1][:60] if app_row[1] else "Role"  # use JD start as fallback
        # prefer company name from DB row
        folder_name = f"{company_name} - Interview Pack" if company_name else "Interview Pack"
        company_slug = (company_name or "Company").replace(".", "").replace(" ", "_")
        pdf_filename = f"InterviewPack_{company_slug}.pdf"
        docx_filename = f"InterviewPack_{company_slug}.docx"

        # Fetch the actual job title from job_postings for a better label
        if job_posting_id:
            jp_row = await db.execute(
                text("SELECT title FROM job_postings WHERE id = :jid"),
                {"jid": job_posting_id},
            )
            jp = jp_row.first()
            if jp and jp[0]:
                job_title = jp[0]

        drive_file_id: str | None = None
        drive_link: str | None = None
        drive_error: str | None = None
        try:
            docx_bytes = build_interview_pack_docx(result, company_name, job_title)
            pdf_bytes, conv_token_data = await convert_docx_to_pdf_bytes(
                access_token=prof["google_access_token"],
                refresh_token=prof["google_refresh_token"],
                expiry_iso=prof["google_token_expiry"],
                docx_bytes=docx_bytes,
                filename=docx_filename,
            )
            upload_access_token = prof["google_access_token"]
            upload_expiry = prof["google_token_expiry"]
            if conv_token_data:
                upload_access_token = conv_token_data["access_token"]
                upload_expiry = conv_token_data["expiry_iso"]
                await db.execute(
                    text("UPDATE profiles SET google_access_token=:at, google_token_expiry=:exp WHERE user_id=:uid"),
                    {"at": upload_access_token, "exp": upload_expiry, "uid": current_user.id},
                )

            file_id, web_link, new_token_data = await upload_or_update_file(
                access_token=upload_access_token,
                refresh_token=prof["google_refresh_token"],
                expiry_iso=upload_expiry,
                folder_name=folder_name,
                filename=pdf_filename,
                file_bytes=pdf_bytes,
            )
            if new_token_data:
                await db.execute(
                    text("UPDATE profiles SET google_access_token=:at, google_token_expiry=:exp WHERE user_id=:uid"),
                    {"at": new_token_data["access_token"], "exp": new_token_data["expiry_iso"], "uid": current_user.id},
                )

            drive_file_id = file_id
            drive_link = web_link

            # Clear content from DB, keep row for Drive link persistence
            await db.execute(
                text("""
                    UPDATE interview_packs
                    SET pitch = '', star_questions = '[]',
                        drive_file_id = :fid, drive_link = :link,
                        updated_at = now()
                    WHERE application_id = :app_id AND user_id = :uid
                """),
                {"fid": file_id, "link": web_link,
                 "app_id": request.application_id, "uid": current_user.id},
            )
            await db.commit()
        except Exception as exc:
            logger.error("interview_from_job: Drive upload failed — %s", exc, exc_info=True)
            drive_error = str(exc)

        return {
            "pitch": result.pitch,
            "star_questions": [q.model_dump() for q in result.star_questions],
            "drive_file_id": drive_file_id,
            "drive_link": drive_link,
            "drive_error": drive_error,
        }

    # Drive not connected — pack already saved to DB by the agent
    return {
        "pitch": result.pitch,
        "star_questions": [q.model_dump() for q in result.star_questions],
        "drive_file_id": None,
        "drive_link": None,
        "drive_error": None,
    }


@router.get("/agents/interview-pack/{application_id}")
async def get_interview_pack(
    application_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a cached interview pack for an application. 404 if not yet generated."""
    row = await db.execute(
        text("""
            SELECT ip.pitch, ip.star_questions, ip.updated_at
            FROM interview_packs ip
            JOIN applications a ON a.id = ip.application_id
            WHERE ip.application_id = :app_id AND a.user_id = :uid
        """),
        {"app_id": application_id, "uid": current_user.id},
    )
    pack = row.first()
    if not pack:
        raise HTTPException(status_code=404, detail="Interview pack not found.")

    import json as _json
    return {
        "application_id": application_id,
        "pitch": pack[0],
        "star_questions": _json.loads(pack[1]),
        "updated_at": pack[2].isoformat() if pack[2] else None,
    }


@router.post("/agents/run")
async def run_agent_session(
    request: RunSessionRequest,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger a full LangGraph session (background). Returns session_id immediately.
    Poll GET /agents/sessions/{id} for status.
    """
    import uuid
    session_id = str(uuid.uuid4())

    # Record session start
    await db.execute(
        text("""
            INSERT INTO agent_jobs
                (session_id, user_id, status, priority, params_json, created_at)
            VALUES (:sid, :uid, 'queued', 1, :params, :now)
        """),
        {
            "sid": session_id,
            "uid": current_user.id,
            "params": json.dumps({
                "job_postings": request.job_postings,
                "job_description": request.job_description,
                "trigger": request.trigger,
            }),
            "now": now_utc(),
        },
    )
    await db.commit()

    async def _run_in_background():
        try:
            await db.execute(
                text("UPDATE agent_jobs SET status='running', started_at=:now WHERE session_id=:sid"),
                {"now": now_utc(), "sid": session_id},
            )
            await db.commit()

            final_state = await run_session(
                user_id=current_user.id,
                job_postings=request.job_postings,
                job_description=request.job_description,
                trigger=request.trigger,
            )

            await db.execute(
                text("""
                    UPDATE agent_jobs
                    SET status='complete', completed_at=:now,
                        result_json=:result
                    WHERE session_id=:sid
                """),
                {
                    "now": now_utc(),
                    "sid": session_id,
                    "result": json.dumps({
                        "current_node": final_state.get("current_node"),
                        "errors": [e.model_dump() if hasattr(e, "model_dump") else str(e)
                                   for e in final_state.get("errors", [])],
                    }, default=str),
                },
            )
            await db.commit()
        except Exception as exc:
            await db.execute(
                text("""
                    UPDATE agent_jobs
                    SET status='failed', completed_at=:now,
                        error_message=:err
                    WHERE session_id=:sid
                """),
                {
                    "now": now_utc(),
                    "sid": session_id,
                    "err": str(exc),
                },
            )
            await db.commit()

    background_tasks.add_task(_run_in_background)

    return {"session_id": session_id, "status": "queued"}


@router.get("/agents/sessions/{session_id}")
async def get_session(
    session_id: str,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get status of a LangGraph session."""
    row = await db.execute(
        text("""
            SELECT session_id, status, params_json, result_json, error_message,
                   created_at, started_at, completed_at
            FROM agent_jobs
            WHERE session_id = :sid AND user_id = :uid
        """),
        {"sid": session_id, "uid": current_user.id},
    )
    job = row.mappings().first()
    if not job:
        raise HTTPException(status_code=404, detail="Session not found")

    return dict(job)


@router.get("/agents/runs/{run_id}")
async def get_run(
    run_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single agent_run record."""
    row = await db.execute(
        text("""
            SELECT id, agent_name, reasoning_pattern, status, attempt_number,
                   input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
                   cost_usd, started_at, completed_at, final_output
            FROM agent_runs
            WHERE id = :rid AND user_id = :uid
        """),
        {"rid": run_id, "uid": current_user.id},
    )
    run = row.mappings().first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return dict(run)


# ---------------------------------------------------------------------------
# Approval / draft endpoints
# ---------------------------------------------------------------------------

@router.get("/approvals/pending")
async def pending_approvals(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all drafts pending human review."""
    rows = await db.execute(
        text("""
            SELECT d.id, d.draft_type, d.gate_tier, d.content, d.status,
                   d.created_at, a.company_name, a.role_title
            FROM drafts d
            LEFT JOIN applications a ON d.application_id = a.id
            WHERE d.user_id = :uid AND d.status = 'pending'
            ORDER BY d.created_at DESC
        """),
        {"uid": current_user.id},
    )
    return {"drafts": [dict(r) for r in rows.mappings()]}


@router.post("/approvals/{draft_id}/approve")
async def approve_draft(
    draft_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _update_draft_status(db, draft_id, current_user.id, "approved", None)
    return {"status": "approved"}


@router.post("/approvals/{draft_id}/edit")
async def edit_draft(
    draft_id: int,
    body: ApprovalEditRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _update_draft_status(db, draft_id, current_user.id, "edited", body.edited_content)
    return {"status": "edited"}


@router.post("/approvals/{draft_id}/reject")
async def reject_draft(
    draft_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _update_draft_status(db, draft_id, current_user.id, "rejected", None)
    return {"status": "rejected"}


async def _update_draft_status(
    db: AsyncSession,
    draft_id: int,
    user_id: int,
    status: str,
    edited_content: Optional[str],
):
    row = await db.execute(
        text("SELECT id FROM drafts WHERE id = :did AND user_id = :uid"),
        {"did": draft_id, "uid": user_id},
    )
    if not row.fetchone():
        raise HTTPException(status_code=404, detail="Draft not found")

    await db.execute(
        text("""
            UPDATE drafts
            SET status = :status,
                user_edited_content = :edited,
                reviewed_at = :now
            WHERE id = :did
        """),
        {
            "status": status,
            "edited": edited_content,
            "now": now_utc(),
            "did": draft_id,
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Budget + Audit endpoints
# ---------------------------------------------------------------------------

@router.get("/budget/summary")
async def budget_summary(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Daily cost breakdown per agent, last 30 days."""
    rows = await db.execute(
        text("""
            SELECT date, agent_name,
                   total_input_tokens, total_output_tokens,
                   total_cache_read_tokens, total_cache_creation_tokens,
                   total_cost_usd, call_count
            FROM budget_records
            ORDER BY date DESC, agent_name
            LIMIT 300
        """)
    )
    records = [dict(r) for r in rows.mappings()]

    total_cost = sum(r["total_cost_usd"] for r in records)
    cache_read = sum(r["total_cache_read_tokens"] for r in records)
    all_input = sum(r["total_input_tokens"] for r in records)
    cache_hit_rate = (cache_read / all_input) if all_input > 0 else 0.0

    return {
        "records": records,
        "total_cost_usd": round(total_cost, 6),
        "cache_hit_rate": round(cache_hit_rate, 4),
    }


@router.get("/audit/log")
async def audit_log(
    limit: int = 50,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent audit log entries."""
    rows = await db.execute(
        text("""
            SELECT id, event_type, actor, entity_type, entity_id,
                   payload, chain_hash, timestamp
            FROM audit_log
            ORDER BY id DESC
            LIMIT :limit
        """),
        {"limit": min(limit, 200)},
    )
    return {"entries": [dict(r) for r in rows.mappings()]}


@router.get("/audit/verify")
async def audit_verify(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Verify audit log hash-chain integrity.
    Returns {"valid": true} or {"valid": false, "broken_at_id": N}.
    """
    from app.shared.logger import AuditLogger
    logger = AuditLogger()
    valid, broken_ids = await logger.verify_chain(db)
    if valid:
        return {"valid": True, "message": "Chain intact"}
    return {"valid": False, "broken_ids": broken_ids}


# ---------------------------------------------------------------------------
# Job feedback endpoints
# ---------------------------------------------------------------------------

class JobFeedbackRequest(BaseModel):
    job_url: str
    job_title: str
    company: str
    relevance: str        # relevant | not_relevant
    reason: str | None = None  # why not relevant — required for not_relevant, null for relevant


@router.post("/research/feedback")
async def save_job_feedback(
    body: JobFeedbackRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save or update relevance feedback for a job posting."""
    if body.relevance not in ("relevant", "not_relevant"):
        raise HTTPException(status_code=422, detail="relevance must be 'relevant' or 'not_relevant'")

    await db.execute(
        text("""
            INSERT INTO job_feedback (user_id, job_url, job_title, company, relevance, reason, created_at, updated_at)
            VALUES (:uid, :url, :title, :company, :relevance, :reason, :now, :now)
            ON CONFLICT(user_id, job_url) DO UPDATE SET
                relevance  = excluded.relevance,
                reason     = excluded.reason,
                updated_at = excluded.updated_at
        """),
        {
            "uid":      current_user.id,
            "url":      body.job_url,
            "title":    body.job_title,
            "company":  body.company,
            "relevance": body.relevance,
            "reason":   body.reason,
            "now":      now_utc(),
        },
    )
    await db.commit()
    return {"status": "saved"}


@router.get("/research/jobs")
async def get_stored_jobs(
    page: int = 1,
    per_page: int = 20,
    role: str = "",
    days: int = 0,
    min_score: float = 0.0,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return paginated stored job postings for the current user.
    Ordered by posted_at DESC (most recent first).
    Optionally filter by role title, recency (days), and minimum fit score.
    Jobs whose inferred_industries don't match the user's target_industries are excluded.
    Jobs with no inferred industries (empty list) are always shown.
    """
    import json as _json
    offset = (page - 1) * per_page

    # Load user's target industries for server-side filtering
    profile = await _load_profile(db, current_user.id)
    target_industries: list[str] = profile.get("industries") or []

    ujp_where = [
        "ujp.user_id = :uid",
        "ujp.archived = false",
        "(ujp.scored = true OR ujp.rescoring = true)",
        "jp.id NOT IN (SELECT job_posting_id FROM applications WHERE user_id = :uid AND job_posting_id IS NOT NULL)",
    ]
    params: dict = {"uid": current_user.id, "limit": per_page, "offset": offset}

    # Industry filter: pass jobs with no industries, exclude those that don't match
    if target_industries:
        ind_placeholders = ",".join(f":ind{i}" for i in range(len(target_industries)))
        ujp_where.append(
            f"(jp.inferred_industries = '[]' OR jp.inferred_industries IS NULL OR "
            f"EXISTS (SELECT 1 FROM json_array_elements_text(jp.inferred_industries::json) AS v WHERE v IN ({ind_placeholders})))"
        )
        for i, ind in enumerate(target_industries):
            params[f"ind{i}"] = ind

    if role:
        ujp_where.append("jp.title LIKE :role")
        params["role"] = f"%{role}%"

    if days > 0:
        ujp_where.append("jp.posted_at >= NOW() - INTERVAL '1 day' * :cutoff")
        params["cutoff"] = days

    if min_score > 0:
        ujp_where.append("ujp.fit_score >= :min_score")
        params["min_score"] = min_score

    where_sql = " AND ".join(ujp_where)

    count_row = await db.execute(
        text(f"""
            SELECT COUNT(*)
            FROM user_job_postings ujp
            JOIN job_postings jp ON jp.id = ujp.job_posting_id
            WHERE {where_sql}
        """),
        params,
    )
    total = count_row.scalar_one()

    rows = await db.execute(
        text(f"""
            SELECT jp.id, jp.mcf_uuid, jp.title, jp.company, jp.url, jp.location,
                   jp.inferred_industries, jp.posted_at, jp.scraped_at,
                   ujp.scored, ujp.fit_score, ujp.reasons, ujp.risks, ujp.key_keywords,
                   ujp.scoring_breakdown, ujp.recommendation, ujp.score_error,
                   ujp.scored_at, ujp.scored_by_model, ujp.rescoring
            FROM user_job_postings ujp
            JOIN job_postings jp ON jp.id = ujp.job_posting_id
            WHERE {where_sql}
            ORDER BY jp.posted_at DESC, jp.scraped_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    jobs = [dict(r) for r in rows.mappings()]
    return {"total": total, "page": page, "per_page": per_page, "jobs": jobs}


@router.get("/research/jobs/selected")
async def get_selected_jobs(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return job postings the user has saved to Selected Jobs.
    Joins job_postings with applications where status='selected'.
    """
    rows = await db.execute(
        text("""
            SELECT jp.id, jp.mcf_uuid, jp.title, jp.company, jp.url, jp.location,
                   jp.inferred_industries, jp.posted_at, jp.scraped_at,
                   ujp.scored, ujp.fit_score, ujp.reasons, ujp.risks, ujp.key_keywords,
                   ujp.scoring_breakdown, ujp.recommendation, ujp.score_error,
                   ujp.scored_at, ujp.scored_by_model, ujp.archived,
                   a.id AS application_id
            FROM job_postings jp
            JOIN user_job_postings ujp ON ujp.job_posting_id = jp.id AND ujp.user_id = :uid
            JOIN applications a
              ON a.job_posting_id = jp.id
             AND a.user_id = :uid
             AND a.status = 'selected'
            ORDER BY a.created_at DESC
        """),
        {"uid": current_user.id},
    )
    jobs = [dict(r) for r in rows.mappings()]
    return {"total": len(jobs), "jobs": jobs}


@router.get("/research/jobs/applied")
async def get_applied_jobs(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return job postings the user has marked as applied."""
    rows = await db.execute(
        text("""
            SELECT jp.id, jp.mcf_uuid, jp.title, jp.company, jp.url, jp.location,
                   jp.inferred_industries, jp.posted_at, jp.scraped_at,
                   ujp.scored, ujp.fit_score, ujp.reasons, ujp.risks, ujp.key_keywords,
                   ujp.scoring_breakdown, ujp.recommendation, ujp.score_error,
                   ujp.scored_at, ujp.scored_by_model, ujp.archived,
                   a.id AS application_id, a.applied_at
            FROM job_postings jp
            JOIN user_job_postings ujp ON ujp.job_posting_id = jp.id AND ujp.user_id = :uid
            JOIN applications a
              ON a.job_posting_id = jp.id
             AND a.user_id = :uid
             AND a.status = 'applied'
            ORDER BY a.updated_at DESC
        """),
        {"uid": current_user.id},
    )
    jobs = [dict(r) for r in rows.mappings()]
    return {"total": len(jobs), "jobs": jobs}


@router.get("/research/jobs/interviewing")
async def get_interviewing_jobs(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return jobs the user has moved to interviewing, offered, or rejected."""
    rows = await db.execute(
        text("""
            SELECT jp.id, jp.mcf_uuid, jp.title, jp.company, jp.url, jp.location,
                   jp.inferred_industries, jp.posted_at, jp.scraped_at,
                   ujp.scored, ujp.fit_score, ujp.reasons, ujp.risks, ujp.key_keywords,
                   ujp.scoring_breakdown, ujp.recommendation, ujp.score_error,
                   ujp.scored_at, ujp.scored_by_model, ujp.archived,
                   a.id AS application_id, a.status AS application_status, a.applied_at,
                   (ip.id IS NOT NULL AND (ip.pitch != '' OR ip.drive_file_id IS NOT NULL)) AS has_interview_pack,
                   ip.drive_file_id AS pack_drive_file_id,
                   ip.drive_link AS pack_drive_link
            FROM job_postings jp
            JOIN user_job_postings ujp ON ujp.job_posting_id = jp.id AND ujp.user_id = :uid
            JOIN applications a
              ON a.job_posting_id = jp.id
             AND a.user_id = :uid
             AND a.status IN ('interviewing', 'offered', 'rejected')
            LEFT JOIN interview_packs ip ON ip.application_id = a.id
            ORDER BY a.updated_at DESC
        """),
        {"uid": current_user.id},
    )
    jobs = [dict(r) for r in rows.mappings()]
    return {"total": len(jobs), "jobs": jobs}


class BulkArchiveRequest(BaseModel):
    job_ids: list[int] = Field(min_length=1, max_length=500)


@router.post("/research/jobs/bulk-archive", status_code=204)
async def bulk_archive_jobs(
    body: BulkArchiveRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Archive multiple job postings in one call. Silently ignores IDs not owned by the user."""
    if not body.job_ids:
        return
    placeholders = ",".join(f":id{i}" for i in range(len(body.job_ids)))
    params = {"uid": current_user.id}
    for i, jid in enumerate(body.job_ids):
        params[f"id{i}"] = jid
    await db.execute(
        text(f"UPDATE user_job_postings SET archived = true WHERE user_id = :uid AND job_posting_id IN ({placeholders})"),
        params,
    )
    await db.commit()


class BulkRescoreRequest(BaseModel):
    job_ids: list[int] = Field(min_length=2, max_length=100)


@router.post("/research/jobs/bulk-rescore")
async def bulk_rescore_jobs(
    body: BulkRescoreRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Score multiple jobs in one LLM call. Returns updated job rows keyed by id."""
    from app.pipeline.llm_scorer import score_jobs_by_ids

    # Verify ownership via user_job_postings — silently drop IDs not owned by this user
    placeholders = ",".join(f":id{i}" for i in range(len(body.job_ids)))
    params: dict = {"uid": current_user.id}
    for i, jid in enumerate(body.job_ids):
        params[f"id{i}"] = jid

    owned = await db.execute(
        text(f"SELECT job_posting_id FROM user_job_postings WHERE user_id = :uid AND job_posting_id IN ({placeholders})"),
        params,
    )
    owned_ids = [r[0] for r in owned.fetchall()]
    if not owned_ids:
        raise HTTPException(404, "No owned jobs found")

    await score_jobs_by_ids(db, owned_ids, user_id=current_user.id)

    # Fetch and return updated rows
    owned_placeholders = ",".join(f":id{i}" for i in range(len(owned_ids)))
    owned_params: dict = {"uid": current_user.id}
    for i, jid in enumerate(owned_ids):
        owned_params[f"id{i}"] = jid
    rows = await db.execute(
        text(f"""
            SELECT jp.id, jp.mcf_uuid, jp.title, jp.company, jp.url, jp.location,
                   jp.inferred_industries, jp.posted_at, jp.scraped_at,
                   ujp.scored, ujp.fit_score, ujp.reasons, ujp.risks, ujp.key_keywords,
                   ujp.scoring_breakdown, ujp.recommendation, ujp.score_error,
                   ujp.scored_at, ujp.scored_by_model, ujp.rescoring
            FROM job_postings jp
            JOIN user_job_postings ujp ON ujp.job_posting_id = jp.id AND ujp.user_id = :uid
            WHERE jp.id IN ({owned_placeholders})
        """),
        owned_params,
    )
    jobs = [dict(r) for r in rows.mappings().all()]
    return {"jobs": jobs}


@router.post("/research/jobs/{job_id}/archive", status_code=204)
async def archive_job(
    job_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a job posting as archived — it will no longer appear in the research panel."""
    result = await db.execute(
        text("SELECT id FROM user_job_postings WHERE job_posting_id = :id AND user_id = :uid"),
        {"id": job_id, "uid": current_user.id},
    )
    if not result.fetchone():
        raise HTTPException(404, "Job not found")
    await db.execute(
        text("UPDATE user_job_postings SET archived = true WHERE job_posting_id = :id AND user_id = :uid"),
        {"id": job_id, "uid": current_user.id},
    )
    await db.commit()


@router.post("/research/jobs/{job_id}/rescore")
async def rescore_job(
    job_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Score a single job immediately and return the updated job row."""
    from app.pipeline.llm_scorer import score_single_job  # local import avoids circular dep

    result = await db.execute(
        text("SELECT id FROM user_job_postings WHERE job_posting_id = :id AND user_id = :uid"),
        {"id": job_id, "uid": current_user.id},
    )
    if not result.fetchone():
        raise HTTPException(404, "Job not found")

    await score_single_job(db, job_id, user_id=current_user.id)

    row = await db.execute(
        text("""
            SELECT jp.id, jp.mcf_uuid, jp.title, jp.company, jp.url, jp.location,
                   jp.inferred_industries, jp.posted_at, jp.scraped_at,
                   ujp.scored, ujp.fit_score, ujp.reasons, ujp.risks, ujp.key_keywords,
                   ujp.scoring_breakdown, ujp.recommendation, ujp.score_error,
                   ujp.scored_at, ujp.scored_by_model, ujp.rescoring
            FROM job_postings jp
            JOIN user_job_postings ujp ON ujp.job_posting_id = jp.id AND ujp.user_id = :uid
            WHERE jp.id = :id
        """),
        {"id": job_id, "uid": current_user.id},
    )
    job = row.mappings().first()
    return dict(job) if job else {}


class GenerateResumeRequest(BaseModel):
    additional_context: str = ""


@router.post("/research/jobs/{job_id}/generate-resume")
async def generate_resume(
    job_id: int,
    body: GenerateResumeRequest = GenerateResumeRequest(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a tailored resume for a selected job, then auto-upload to Google Drive.

    Response codes:
    - 201: Generation + Drive upload both succeeded; resume_json cleared from DB.
    - 207: Generation succeeded but Drive upload failed; resume_json retained for retry.
    - 422: No resume in profile, or Google Drive not connected.
    - 502: LLM generation failed.
    """
    from fastapi.responses import JSONResponse
    from app.modules.agents.resume_generate_agent import run_resume_generate_agent
    from app.shared.schemas import AgentError
    from app.shared.resume_docx import build_docx_bytes
    from app.shared.google_drive import upload_or_update_file, convert_docx_to_pdf_bytes

    # Fetch job (ownership via user_job_postings)
    job_row = await db.execute(
        text("""
            SELECT jp.id, jp.title, jp.company, jp.description
            FROM job_postings jp
            JOIN user_job_postings ujp ON ujp.job_posting_id = jp.id AND ujp.user_id = :uid
            WHERE jp.id = :id
        """),
        {"id": job_id, "uid": current_user.id},
    )
    job = job_row.mappings().first()
    if not job:
        raise HTTPException(404, "Job not found")

    # Fetch profile
    profile = await _load_profile(db, current_user.id)
    resume_text = profile.get("resume_text") or ""
    if not resume_text.strip():
        raise HTTPException(422, "No resume found in profile. Please upload your resume first.")

    # Check Drive connection before generating (fail fast)
    prof_result = await db.execute(
        text("SELECT google_access_token, google_refresh_token, google_token_expiry FROM profiles WHERE user_id = :uid"),
        {"uid": current_user.id},
    )
    prof = prof_result.mappings().first()
    if not prof or not prof["google_refresh_token"]:
        raise HTTPException(422, "Google Drive not connected. Connect Drive first before generating a resume.")

    candidate_name = profile.get("full_name") or ""

    # Fetch linked application_id if exists
    app_row = await db.execute(
        text("""
            SELECT id FROM applications
            WHERE job_posting_id = :jid AND user_id = :uid AND status = 'selected'
            LIMIT 1
        """),
        {"jid": job_id, "uid": current_user.id},
    )
    app = app_row.mappings().first()
    application_id = app["id"] if app else None

    # ── LLM generation ───────────────────────────────────────────────────────
    result, _ = await run_resume_generate_agent(
        resume_text=resume_text,
        jd_text=job["description"] or "",
        candidate_name=candidate_name,
        additional_context=body.additional_context,
        db=db,
        user_id=current_user.id,
        application_id=application_id,
    )

    if isinstance(result, AgentError):
        raise HTTPException(502, f"Resume generation failed: {result.error}")

    now = now_utc()
    resume_json = result.model_dump_json()

    # ── Persist generated resume (always save JSON first as safety net) ──────
    await db.execute(
        text("""
            INSERT INTO generated_resumes
                (user_id, job_posting_id, application_id, resume_json, created_at, updated_at)
            VALUES
                (:uid, :jid, :aid, :resume_json, :now, :now)
            ON CONFLICT (user_id, job_posting_id) DO UPDATE SET
                resume_json    = excluded.resume_json,
                application_id = excluded.application_id,
                drive_file_id  = NULL,
                drive_link     = NULL,
                updated_at     = excluded.updated_at
        """),
        {"uid": current_user.id, "jid": job_id, "aid": application_id,
         "resume_json": resume_json, "now": now},
    )
    await db.commit()

    # ── Build .docx → convert to PDF → upload to Drive ──────────────────────
    company = job["company"] or "Company"
    title = job["title"] or "Role"
    folder_name = f"{company} - {title}"
    company_slug = company.replace(".", "").replace(" ", "_")
    docx_filename = f"Resume_{company_slug}.docx"
    pdf_filename  = f"Resume_{company_slug}.pdf"

    # Load existing drive_file_id for update-vs-create decision
    gr_result = await db.execute(
        text("SELECT drive_file_id FROM generated_resumes WHERE user_id = :uid AND job_posting_id = :jid"),
        {"uid": current_user.id, "jid": job_id},
    )
    gr = gr_result.mappings().first()
    existing_file_id = gr["drive_file_id"] if gr else None

    drive_error: str | None = None
    drive_file_id: str | None = None
    drive_link: str | None = None

    try:
        docx_bytes = build_docx_bytes(result)
        # Convert .docx → PDF via Drive API (import as Google Doc, export PDF, delete temp)
        pdf_bytes, conv_token_data = await convert_docx_to_pdf_bytes(
            access_token=prof["google_access_token"],
            refresh_token=prof["google_refresh_token"],
            expiry_iso=prof["google_token_expiry"],
            docx_bytes=docx_bytes,
            filename=docx_filename,
        )
        # Persist refreshed tokens from conversion step if rotated
        if conv_token_data:
            prof = dict(prof)
            prof["google_access_token"] = conv_token_data["access_token"]
            prof["google_token_expiry"] = conv_token_data["expiry_iso"]
            await db.execute(
                text("UPDATE profiles SET google_access_token=:at, google_token_expiry=:exp WHERE user_id=:uid"),
                {"at": conv_token_data["access_token"], "exp": conv_token_data["expiry_iso"], "uid": current_user.id},
            )

        file_id, web_link, new_token_data = await upload_or_update_file(
            access_token=prof["google_access_token"],
            refresh_token=prof["google_refresh_token"],
            expiry_iso=prof["google_token_expiry"],
            folder_name=folder_name,
            filename=pdf_filename,
            file_bytes=pdf_bytes,
            existing_file_id=existing_file_id,
        )
        drive_file_id = file_id
        drive_link = web_link

        # Persist refreshed tokens if rotated
        if new_token_data:
            await db.execute(
                text("UPDATE profiles SET google_access_token=:at, google_token_expiry=:exp WHERE user_id=:uid"),
                {"at": new_token_data["access_token"], "exp": new_token_data["expiry_iso"], "uid": current_user.id},
            )

        # Success: store drive info, clear resume_json (sentinel '{}' — column is NOT NULL)
        await db.execute(
            text("""
                UPDATE generated_resumes
                SET drive_file_id = :fid,
                    drive_link    = :link,
                    resume_json   = '{}',
                    updated_at    = :now
                WHERE user_id = :uid AND job_posting_id = :jid
            """),
            {"fid": drive_file_id, "link": drive_link, "now": now,
             "uid": current_user.id, "jid": job_id},
        )
        await db.commit()

        logger.info(
            "generate_resume: Drive upload success — user_id=%d job_id=%d file_id=%s",
            current_user.id, job_id, drive_file_id,
        )

    except Exception as exc:
        logger.error(
            "generate_resume: Drive upload failed — user_id=%d job_id=%d: %s",
            current_user.id, job_id, exc, exc_info=True,
        )
        drive_error = str(exc)

    payload = {
        "job_posting_id": job_id,
        "resume": result.model_dump(),
        "drive_file_id": drive_file_id,
        "drive_link": drive_link,
    }

    if drive_error:
        payload["drive_error"] = drive_error
        return JSONResponse(status_code=207, content=payload)

    return JSONResponse(status_code=201, content=payload)


@router.post("/research/jobs/{job_id}/retry-drive-upload", status_code=201)
async def retry_drive_upload(
    job_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-attempt Drive upload for a resume where generation succeeded but upload failed.
    Requires resume_json to still be present in generated_resumes.
    On success, clears resume_json from the DB row.
    """
    from fastapi.responses import JSONResponse
    from app.shared.schemas import GeneratedResumeOutput
    from app.shared.resume_docx import build_docx_bytes
    from app.shared.google_drive import upload_or_update_file, convert_docx_to_pdf_bytes
    import json as _json

    # Load OAuth tokens
    prof_result = await db.execute(
        text("SELECT google_access_token, google_refresh_token, google_token_expiry FROM profiles WHERE user_id = :uid"),
        {"uid": current_user.id},
    )
    prof = prof_result.mappings().first()
    if not prof or not prof["google_refresh_token"]:
        raise HTTPException(422, "Google Drive not connected.")

    # Load stored resume JSON
    gr_result = await db.execute(
        text("SELECT resume_json, drive_file_id FROM generated_resumes WHERE user_id=:uid AND job_posting_id=:jid"),
        {"uid": current_user.id, "jid": job_id},
    )
    gr = gr_result.mappings().first()
    if not gr or not gr["resume_json"]:
        raise HTTPException(404, "No stored resume found for retry. Please generate first.")

    # Load job info for folder/filename
    job_result = await db.execute(
        text("SELECT title, company FROM job_postings WHERE id=:jid AND user_id=:uid"),
        {"jid": job_id, "uid": current_user.id},
    )
    job = job_result.mappings().first()
    if not job:
        raise HTTPException(404, "Job not found")

    resume = GeneratedResumeOutput.model_validate(_json.loads(gr["resume_json"]))
    company = job["company"] or "Company"
    title_str = job["title"] or "Role"
    folder_name = f"{company} - {title_str}"
    company_slug = company.replace(".", "").replace(" ", "_")
    docx_filename = f"Resume_{company_slug}.docx"
    pdf_filename  = f"Resume_{company_slug}.pdf"

    conv_token_data: dict | None = None
    try:
        docx_bytes = build_docx_bytes(resume)
        # Convert .docx → PDF via Drive API before uploading
        pdf_bytes, conv_token_data = await convert_docx_to_pdf_bytes(
            access_token=prof["google_access_token"],
            refresh_token=prof["google_refresh_token"],
            expiry_iso=prof["google_token_expiry"],
            docx_bytes=docx_bytes,
            filename=docx_filename,
        )
        if conv_token_data:
            prof = dict(prof)
            prof["google_access_token"] = conv_token_data["access_token"]
            prof["google_token_expiry"] = conv_token_data["expiry_iso"]

        file_id, web_link, new_token_data = await upload_or_update_file(
            access_token=prof["google_access_token"],
            refresh_token=prof["google_refresh_token"],
            expiry_iso=prof["google_token_expiry"],
            folder_name=folder_name,
            filename=pdf_filename,
            file_bytes=pdf_bytes,
            existing_file_id=gr["drive_file_id"],
        )
    except Exception as exc:
        logger.error(
            "retry_drive_upload: failed — user_id=%d job_id=%d: %s",
            current_user.id, job_id, exc, exc_info=True,
        )
        raise HTTPException(502, f"Google Drive upload failed: {exc}")

    now = now_utc()

    # Persist any refreshed token from conversion or upload step
    merged_token = new_token_data or conv_token_data
    if merged_token:
        await db.execute(
            text("UPDATE profiles SET google_access_token=:at, google_token_expiry=:exp WHERE user_id=:uid"),
            {"at": merged_token["access_token"], "exp": merged_token["expiry_iso"], "uid": current_user.id},
        )

    await db.execute(
        text("""
            UPDATE generated_resumes
            SET drive_file_id = :fid,
                drive_link    = :link,
                resume_json   = '{}',
                updated_at    = :now
            WHERE user_id = :uid AND job_posting_id = :jid
        """),
        {"fid": file_id, "link": web_link, "now": now,
         "uid": current_user.id, "jid": job_id},
    )
    await db.commit()

    logger.info(
        "retry_drive_upload: success — user_id=%d job_id=%d file_id=%s",
        current_user.id, job_id, file_id,
    )

    return {
        "job_posting_id": job_id,
        "resume": resume.model_dump(),
        "drive_file_id": file_id,
        "drive_link": web_link,
    }


@router.post("/research/jobs/rescore-all")
async def rescore_all_jobs(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rescore every unarchived job for the current user in batches of scorer_batch_size."""
    from app.pipeline.llm_scorer import score_jobs_by_ids
    from app.shared.config import get_settings

    rows = await db.execute(
        text("SELECT id FROM job_postings WHERE user_id = :uid AND archived = false"),
        {"uid": current_user.id},
    )
    all_ids = [r[0] for r in rows.fetchall()]
    if not all_ids:
        raise HTTPException(404, "No jobs found")

    batch_size = get_settings().scorer_batch_size
    for i in range(0, len(all_ids), batch_size):
        chunk = all_ids[i : i + batch_size]
        await score_jobs_by_ids(db, chunk)

    return {"count": len(all_ids)}


class BulkGenerateResumeRequest(BaseModel):
    job_ids: list[int] = Field(min_length=1, max_length=100)


@router.post("/research/jobs/bulk-generate-resume", status_code=202)
async def bulk_generate_resumes(
    body: BulkGenerateResumeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate tailored resumes for multiple jobs sequentially.
    Returns {results: {job_id: true/false}}.
    Rate limiting is handled globally by GeminiClient.
    """
    from app.pipeline.resume_generator import generate_resumes_for_jobs

    # Verify ownership — silently drop IDs not owned by this user
    placeholders = ",".join(f":id{i}" for i in range(len(body.job_ids)))
    params: dict = {"uid": current_user.id}
    for i, jid in enumerate(body.job_ids):
        params[f"id{i}"] = jid

    owned = await db.execute(
        text(f"SELECT id FROM job_postings WHERE user_id = :uid AND id IN ({placeholders})"),
        params,
    )
    owned_ids = [r[0] for r in owned.fetchall()]
    if not owned_ids:
        raise HTTPException(404, "No owned jobs found")

    results = await generate_resumes_for_jobs(db, owned_ids, current_user.id)
    return {"results": results}


@router.get("/research/jobs/{job_id}/resume")
async def get_generated_resume(
    job_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the previously generated resume for a job, or 404 if not yet generated.

    Drive fields (drive_file_id, drive_link) are only returned when the user has
    an active Drive OAuth connection. If Drive is not connected, those fields are
    null — preventing exposure of Drive-linked data to unauthenticated sessions.
    """
    row = await db.execute(
        text("""
            SELECT gr.resume_json, gr.drive_file_id, gr.drive_link, gr.created_at, gr.updated_at,
                   p.google_access_token
            FROM generated_resumes gr
            JOIN profiles p ON p.user_id = gr.user_id
            WHERE gr.user_id = :uid AND gr.job_posting_id = :jid
        """),
        {"uid": current_user.id, "jid": job_id},
    )
    resume = row.mappings().first()
    if not resume:
        raise HTTPException(404, "No generated resume found for this job")

    drive_connected = bool(resume["google_access_token"])

    import json as _json
    raw = resume["resume_json"]
    resume_data = _json.loads(raw) if raw and raw != '{}' else None
    return {
        "job_posting_id": job_id,
        "resume": resume_data,
        "drive_file_id": resume["drive_file_id"] if drive_connected else None,
        "drive_link": resume["drive_link"] if drive_connected else None,
        "created_at": resume["created_at"],
        "updated_at": resume["updated_at"],
    }


@router.post("/research/scrape")
async def trigger_scrape(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """On-demand scrape for the current user — same as the daily job but immediate."""
    from app.pipeline.daily_scrape import scrape_for_user
    inserted = await scrape_for_user(current_user.id, db)
    return {"inserted": inserted}


@router.get("/research/feedback")
async def get_job_feedback(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all job feedback for the current user."""
    rows = await db.execute(
        text("""
            SELECT job_url, job_title, company, relevance, reason, created_at
            FROM job_feedback
            WHERE user_id = :uid
            ORDER BY created_at DESC
        """),
        {"uid": current_user.id},
    )
    return {"feedback": [dict(r) for r in rows.mappings()]}


# ---------------------------------------------------------------------------
# Google Drive OAuth2
# ---------------------------------------------------------------------------

@router.get("/auth/google")
async def google_oauth_start(current_user=Depends(get_current_user)):
    """Return the Google OAuth2 authorisation URL with user email encoded in state."""
    from app.shared.google_drive import get_oauth_url
    return {"url": get_oauth_url(state=current_user.email)}


@router.get("/auth/google/callback")
async def google_oauth_callback(
    code: str,
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Exchange authorisation code for tokens and persist them on the profile.

    The user email is passed via the OAuth state parameter so this endpoint
    does not require the X-User-Email header (it's a direct browser redirect
    from Google, not an API call from the frontend).
    """
    from app.shared.google_drive import exchange_code, token_expiry_iso

    if not state:
        raise HTTPException(400, "Missing state parameter — cannot identify user")

    email = state

    # Look up (or create) the user by email
    user_result = await db.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": email},
    )
    user_row = user_result.mappings().first()
    if not user_row:
        raise HTTPException(404, f"User {email} not found")
    uid = user_row["id"]

    try:
        token_data = await exchange_code(code)
    except Exception as exc:
        raise HTTPException(400, f"Google token exchange failed: {exc}")

    expiry = token_expiry_iso(token_data.get("expires_in", 3600))

    # Upsert tokens onto the user's profile
    result = await db.execute(
        text("SELECT id FROM profiles WHERE user_id = :uid"),
        {"uid": uid},
    )
    profile_row = result.mappings().first()
    if profile_row:
        await db.execute(
            text("""
                UPDATE profiles
                SET google_access_token  = :at,
                    google_refresh_token = :rt,
                    google_token_expiry  = :exp
                WHERE user_id = :uid
            """),
            {
                "at": token_data["access_token"],
                "rt": token_data.get("refresh_token"),
                "exp": expiry,
                "uid": uid,
            },
        )
    else:
        await db.execute(
            text("""
                INSERT INTO profiles (user_id, google_access_token, google_refresh_token, google_token_expiry)
                VALUES (:uid, :at, :rt, :exp)
            """),
            {
                "uid": uid,
                "at": token_data["access_token"],
                "rt": token_data.get("refresh_token"),
                "exp": expiry,
            },
        )
    await db.commit()

    # Redirect back to the frontend with a success flag
    return RedirectResponse(f"{get_settings().frontend_url}/?drive=connected")


@router.get("/auth/google/status")
async def google_oauth_status(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return whether the user has connected Google Drive."""
    result = await db.execute(
        text("SELECT google_refresh_token FROM profiles WHERE user_id = :uid"),
        {"uid": current_user.id},
    )
    row = result.mappings().first()
    connected = bool(row and row["google_refresh_token"])
    return {"connected": connected}


@router.delete("/auth/google", status_code=204)
async def google_oauth_disconnect(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove stored OAuth tokens (disconnect Drive). drive_links are retained."""
    await db.execute(
        text("""
            UPDATE profiles
            SET google_access_token  = NULL,
                google_refresh_token = NULL,
                google_token_expiry  = NULL
            WHERE user_id = :uid
        """),
        {"uid": current_user.id},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Upload tailored resume to Google Drive
# ---------------------------------------------------------------------------

@router.post("/research/jobs/{job_id}/upload-to-drive")
async def upload_resume_to_drive(
    job_id: int,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a tailored resume file to the user's Google Drive.

    Folder: My Drive / AI Career Assistant / {Company} - {Job Title} /
    Filename: Resume_{Company}.docx

    If a drive_file_id is already stored, the file is updated (Drive keeps
    version history automatically). Returns { drive_link }.
    """
    from app.shared.google_drive import upload_or_update_file

    # Load OAuth tokens from profile
    prof_result = await db.execute(
        text("""
            SELECT google_access_token, google_refresh_token, google_token_expiry
            FROM profiles WHERE user_id = :uid
        """),
        {"uid": current_user.id},
    )
    prof = prof_result.mappings().first()
    if not prof or not prof["google_refresh_token"]:
        raise HTTPException(403, "Google Drive not connected. Connect Drive first.")

    # Load job info for folder/filename
    job_result = await db.execute(
        text("SELECT title, company FROM job_postings WHERE id = :jid AND user_id = :uid"),
        {"jid": job_id, "uid": current_user.id},
    )
    job = job_result.mappings().first()
    if not job:
        raise HTTPException(404, "Job not found")

    # Load existing drive_file_id if any
    gr_result = await db.execute(
        text("SELECT id, drive_file_id FROM generated_resumes WHERE job_posting_id = :jid AND user_id = :uid"),
        {"jid": job_id, "uid": current_user.id},
    )
    gr = gr_result.mappings().first()
    existing_file_id = gr["drive_file_id"] if gr else None

    company = job["company"]
    title = job["title"]
    folder_name = f"{company} - {title}"
    ext = "." + (file.filename or "resume.docx").rsplit(".", 1)[-1].lower()
    company_slug = company.replace('.', '').replace(' ', '_')
    filename = f"Resume_{company_slug}{ext}"
    file_bytes = await file.read()

    logger.info(
        "upload_resume_to_drive: user_id=%d job_id=%d filename=%r folder=%r existing_file_id=%s",
        current_user.id, job_id, filename, folder_name, existing_file_id,
    )
    try:
        file_id, drive_link, new_token_data = await upload_or_update_file(
            access_token=prof["google_access_token"],
            refresh_token=prof["google_refresh_token"],
            expiry_iso=prof["google_token_expiry"],
            folder_name=folder_name,
            filename=filename,
            file_bytes=file_bytes,
            existing_file_id=existing_file_id,
        )
        logger.info(
            "upload_resume_to_drive: success — user_id=%d job_id=%d file_id=%s",
            current_user.id, job_id, file_id,
        )
    except Exception as exc:
        logger.error(
            "upload_resume_to_drive: Drive upload failed — user_id=%d job_id=%d: %s",
            current_user.id, job_id, exc, exc_info=True,
        )
        raise HTTPException(502, f"Google Drive upload failed: {exc}")

    # Persist refreshed tokens if they were rotated
    if new_token_data:
        await db.execute(
            text("""
                UPDATE profiles
                SET google_access_token = :at, google_token_expiry = :exp
                WHERE user_id = :uid
            """),
            {"at": new_token_data["access_token"], "exp": new_token_data["expiry_iso"], "uid": current_user.id},
        )

    # Store drive_file_id and drive_link on generated_resumes row
    if gr:
        await db.execute(
            text("""
                UPDATE generated_resumes
                SET drive_file_id = :fid, drive_link = :link
                WHERE job_posting_id = :jid AND user_id = :uid
            """),
            {"fid": file_id, "link": drive_link, "jid": job_id, "uid": current_user.id},
        )
    else:
        # No generated resume row yet — store link standalone
        _now = now_utc()
        await db.execute(
            text("""
                INSERT INTO generated_resumes
                    (user_id, job_posting_id, resume_json, drive_file_id, drive_link, created_at, updated_at)
                VALUES (:uid, :jid, '{}', :fid, :link, :now, :now)
            """),
            {"uid": current_user.id, "jid": job_id, "fid": file_id, "link": drive_link, "now": _now},
        )

    await db.commit()
    return {"drive_link": drive_link, "drive_file_id": file_id}
