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
from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.shared.database import get_db
from app.modules.auth.router import get_current_user
from app.modules.agents.research_agent import run_research_agent
from app.modules.agents.resume_agent import run_resume_agent
from app.modules.agents.application_agent import run_application_agent
from app.modules.agents.interview_agent import run_interview_agent
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
                        from app.shared.api_client import get_claude_client
                        client = get_claude_client()
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
    }


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
            "now": datetime.now(timezone.utc).isoformat(),
        },
    )
    await db.commit()

    async def _run_in_background():
        try:
            await db.execute(
                text("UPDATE agent_jobs SET status='running', started_at=:now WHERE session_id=:sid"),
                {"now": datetime.now(timezone.utc).isoformat(), "sid": session_id},
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
                    "now": datetime.now(timezone.utc).isoformat(),
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
                    "now": datetime.now(timezone.utc).isoformat(),
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
            "now": datetime.now(timezone.utc).isoformat(),
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
            "now":      datetime.now(timezone.utc).isoformat(),
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
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return paginated stored job postings for the current user.
    Ordered by posted_at DESC (most recent first).
    Optionally filter by role title and/or recency (days).
    """
    offset = (page - 1) * per_page

    where_clauses = ["user_id = :uid", "archived = 0"]
    params: dict = {"uid": current_user.id, "limit": per_page, "offset": offset}

    if role:
        where_clauses.append("title LIKE :role")
        params["role"] = f"%{role}%"

    if days > 0:
        where_clauses.append(
            "posted_at >= datetime('now', :cutoff)"
        )
        params["cutoff"] = f"-{days} days"

    where_sql = " AND ".join(where_clauses)

    count_row = await db.execute(
        text(f"SELECT COUNT(*) FROM job_postings WHERE {where_sql}"),
        params,
    )
    total = count_row.scalar_one()

    rows = await db.execute(
        text(f"""
            SELECT id, mcf_uuid, title, company, url, location,
                   inferred_industries, posted_at, scraped_at,
                   scored, fit_score, reasons, risks, key_keywords, scoring_breakdown, score_error, scored_at
            FROM job_postings
            WHERE {where_sql}
            ORDER BY posted_at DESC, scraped_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    jobs = [dict(r) for r in rows.mappings()]
    return {"total": total, "page": page, "per_page": per_page, "jobs": jobs}


@router.post("/research/jobs/{job_id}/archive", status_code=204)
async def archive_job(
    job_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a job posting as archived — it will no longer appear in the research panel."""
    result = await db.execute(
        text("SELECT id FROM job_postings WHERE id = :id AND user_id = :uid"),
        {"id": job_id, "uid": current_user.id},
    )
    if not result.fetchone():
        raise HTTPException(404, "Job not found")
    await db.execute(
        text("UPDATE job_postings SET archived = 1 WHERE id = :id AND user_id = :uid"),
        {"id": job_id, "uid": current_user.id},
    )
    await db.commit()


@router.post("/research/jobs/{job_id}/rescore", status_code=204)
async def rescore_job(
    job_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reset a job's score fields so the background scorer loop re-scores it."""
    result = await db.execute(
        text("SELECT id FROM job_postings WHERE id = :id AND user_id = :uid"),
        {"id": job_id, "uid": current_user.id},
    )
    if not result.fetchone():
        raise HTTPException(404, "Job not found")
    await db.execute(
        text("""
            UPDATE job_postings SET
                scored            = 0,
                fit_score         = NULL,
                reasons           = NULL,
                risks             = NULL,
                key_keywords      = NULL,
                scoring_breakdown = NULL,
                score_error       = NULL,
                scored_at         = NULL
            WHERE id = :id AND user_id = :uid
        """),
        {"id": job_id, "uid": current_user.id},
    )
    await db.commit()


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
