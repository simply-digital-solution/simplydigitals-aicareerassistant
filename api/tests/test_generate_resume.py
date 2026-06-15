"""
Tests for resume generation endpoints:
  - POST /research/jobs/{job_id}/generate-resume
  - GET  /research/jobs/{job_id}/resume
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.shared.schemas import GeneratedResumeOutput, GeneratedResumeSection, AgentError

# The agent function is imported locally inside the endpoint, so we patch
# the source module directly so Python's import cache picks up the mock.
_AGENT_PATCH = "app.modules.agents.resume_generate_agent.run_resume_generate_agent"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id: int = 1):
    u = MagicMock()
    u.id = user_id
    return u


def _make_resume_output():
    return GeneratedResumeOutput(
        name="Jane Doe",
        headline="Senior Data Engineer tailored for Fintech",
        sections=[
            GeneratedResumeSection(
                section_type="summary",
                title="Professional Summary",
                content=["Experienced data engineer with 8 years in fintech."],
                experience=[],
            ),
        ],
    )


def _make_profile_orm(resume_text: str = "My resume text here."):
    """Return a MagicMock that mimics a Profile ORM row."""
    p = MagicMock()
    p.full_name = "Jane Doe"
    p.resume_text = resume_text
    p.skills = "[]"
    p.target_titles = "[]"
    p.target_locations = "[]"
    p.target_industries = "[]"
    p.excluded_companies = "[]"
    p.years_experience = 5
    p.salary_floor = None
    p.salary_currency = "SGD"
    p.remote_preference = "any"
    p.employment_type = "any"
    return p


def _db_with_job(has_job: bool = True, resume_text: str = "My resume text here."):
    """
    DB mock serving execute calls in endpoint order:
      1st → job row  (text SELECT)
      2nd → profile  (ORM select → scalar_one_or_none)
      3rd → app link (text SELECT)
      4th → INSERT
    """
    db = AsyncMock()

    # Call 1: job lookup
    job_result = MagicMock()
    job_row = MagicMock()
    job_row.__getitem__ = lambda self, k: "A Python data engineer role." if k == "description" else 1
    job_result.mappings.return_value.first.return_value = job_row if has_job else None

    # Call 2: ORM profile select — _load_profile calls scalar_one_or_none()
    profile_orm_result = MagicMock()
    profile_orm_result.scalar_one_or_none.return_value = _make_profile_orm(resume_text)

    # Call 3: application link
    app_result = MagicMock()
    app_result.mappings.return_value.first.return_value = None

    # Call 4: INSERT
    insert_result = MagicMock()

    db.execute.side_effect = [job_result, profile_orm_result, app_result, insert_result]
    db.commit = AsyncMock()
    return db


def _db_for_get_resume(has_resume: bool = True):
    db = AsyncMock()
    result = MagicMock()
    row = MagicMock()
    row.__getitem__ = lambda self, k: (
        json.dumps(_make_resume_output().model_dump()) if k == "resume_json" else "2026-06-15T00:00:00Z"
    )
    result.mappings.return_value.first.return_value = row if has_resume else None
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# POST /research/jobs/{job_id}/generate-resume
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_resume_returns_resume():
    from app.modules.agents.router import generate_resume

    resume_output = _make_resume_output()
    db = _db_with_job()

    with patch(_AGENT_PATCH, new=AsyncMock(return_value=(resume_output, {}))):
        result = await generate_resume(job_id=1, current_user=_make_user(), db=db)

    assert result["job_posting_id"] == 1
    assert result["resume"]["name"] == "Jane Doe"
    assert result["resume"]["headline"] == "Senior Data Engineer tailored for Fintech"


@pytest.mark.asyncio
async def test_generate_resume_upserts_to_db():
    from app.modules.agents.router import generate_resume

    db = _db_with_job()

    with patch(_AGENT_PATCH, new=AsyncMock(return_value=(_make_resume_output(), {}))):
        await generate_resume(job_id=1, current_user=_make_user(), db=db)

    db.commit.assert_awaited_once()
    # 4 executes: job + profile + app_link + insert
    assert db.execute.await_count == 4


@pytest.mark.asyncio
async def test_generate_resume_404_when_job_not_found():
    from fastapi import HTTPException
    from app.modules.agents.router import generate_resume

    db = _db_with_job(has_job=False)

    # 404 is raised before the agent is called; no patch needed
    with pytest.raises(HTTPException) as exc_info:
        await generate_resume(job_id=999, current_user=_make_user(), db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_generate_resume_422_when_no_resume_in_profile():
    from fastapi import HTTPException
    from app.modules.agents.router import generate_resume

    db = _db_with_job(resume_text="")  # empty resume_text

    # 422 is raised before the agent is called; no patch needed
    with pytest.raises(HTTPException) as exc_info:
        await generate_resume(job_id=1, current_user=_make_user(), db=db)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_generate_resume_502_when_agent_returns_error():
    from fastapi import HTTPException
    from app.modules.agents.router import generate_resume

    db = _db_with_job()
    agent_error = AgentError(error="LLM timeout", raw_output=None)

    with patch(_AGENT_PATCH, new=AsyncMock(return_value=(agent_error, {}))):
        with pytest.raises(HTTPException) as exc_info:
            await generate_resume(job_id=1, current_user=_make_user(), db=db)

    assert exc_info.value.status_code == 502
    assert "LLM timeout" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# GET /research/jobs/{job_id}/resume
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_generated_resume_returns_resume():
    from app.modules.agents.router import get_generated_resume

    db = _db_for_get_resume(has_resume=True)
    result = await get_generated_resume(job_id=1, current_user=_make_user(), db=db)

    assert result["job_posting_id"] == 1
    assert result["resume"]["name"] == "Jane Doe"


@pytest.mark.asyncio
async def test_get_generated_resume_404_when_not_found():
    from fastapi import HTTPException
    from app.modules.agents.router import get_generated_resume

    db = _db_for_get_resume(has_resume=False)
    with pytest.raises(HTTPException) as exc_info:
        await get_generated_resume(job_id=1, current_user=_make_user(), db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_generated_resume_query_filters_by_user():
    from app.modules.agents.router import get_generated_resume

    db = _db_for_get_resume(has_resume=True)
    await get_generated_resume(job_id=5, current_user=_make_user(user_id=99), db=db)

    params = db.execute.call_args.args[1]
    assert params["uid"] == 99
    assert params["jid"] == 5
