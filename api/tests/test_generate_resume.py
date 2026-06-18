"""
Tests for resume generation endpoints:
  - POST /research/jobs/{job_id}/generate-resume
  - GET  /research/jobs/{job_id}/resume
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.shared.schemas import GeneratedResumeOutput, GeneratedResumeSection, AgentError

_AGENT_PATCH   = "app.modules.agents.resume_generate_agent.run_resume_generate_agent"
_DRIVE_PATCH   = "app.shared.google_drive.upload_or_update_file"
_CONVERT_PATCH = "app.shared.google_drive.convert_docx_to_pdf_bytes"
_DOCX_PATCH    = "app.shared.resume_docx.build_docx_bytes"


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


def _make_job_row(has_job: bool = True):
    if not has_job:
        return None
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "id": 1,
        "title": "Data Engineer",
        "company": "ACME Corp",
        "description": "A Python data engineer role.",
    }.get(k)
    return row


def _make_token_row(connected: bool = True, refresh_token: str = "rt123"):
    """Simulate the profiles row for Drive token check."""
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "google_access_token": "at123" if connected else None,
        "google_refresh_token": refresh_token if connected else None,
        "google_token_expiry": "2099-01-01T00:00:00Z" if connected else None,
    }.get(k)
    return row


def _make_db(
    has_job: bool = True,
    resume_text: str = "My resume text here.",
    drive_connected: bool = True,
    existing_drive_file_id=None,
):
    """
    Build an AsyncMock DB that serves execute calls in endpoint order:

    1. Job lookup (text SELECT id, title, company, description)
    2. Profile ORM select → scalar_one_or_none
    3. Drive token check (SELECT google_* FROM profiles)
    4. Application link lookup
    5. INSERT generated_resumes (upsert)
    6. [commit #1]
    7. SELECT drive_file_id (existing file id for Drive update-vs-create)
    8. UPDATE drive fields + clear resume_json
    9. [commit #2]
    """
    db = AsyncMock()

    # 1: job row
    job_result = MagicMock()
    job_result.mappings.return_value.first.return_value = _make_job_row(has_job)

    # 2: ORM profile (used by _load_profile via scalar_one_or_none)
    profile_orm_result = MagicMock()
    profile_orm_result.scalar_one_or_none.return_value = _make_profile_orm(resume_text)

    # 3: Drive token check
    token_result = MagicMock()
    token_result.mappings.return_value.first.return_value = (
        _make_token_row(connected=drive_connected) if drive_connected else None
    )

    # 4: application link
    app_result = MagicMock()
    app_result.mappings.return_value.first.return_value = None

    # 5: INSERT upsert
    insert_result = MagicMock()

    # 6: SELECT drive_file_id for existing_file_id
    gr_row = MagicMock()
    gr_row.__getitem__ = lambda self, k: existing_drive_file_id if k == "drive_file_id" else None
    gr_result = MagicMock()
    gr_result.mappings.return_value.first.return_value = gr_row

    # 7: UPDATE drive fields
    update_result = MagicMock()

    db.execute.side_effect = [
        job_result,
        profile_orm_result,
        token_result,
        app_result,
        insert_result,
        gr_result,
        update_result,
    ]
    db.commit = AsyncMock()
    return db


def _db_for_get_resume(has_resume: bool = True):
    db = AsyncMock()
    result = MagicMock()
    row = MagicMock()
    resume_json = json.dumps(_make_resume_output().model_dump())
    row.__getitem__ = lambda self, k: (
        resume_json if k == "resume_json"
        else (None if k in ("drive_file_id", "drive_link") else "2026-06-15T00:00:00Z")
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
    db = _make_db()

    with patch(_AGENT_PATCH, new=AsyncMock(return_value=(resume_output, {}))):
        with patch(_DOCX_PATCH, return_value=b"fake-docx"):
            with patch(_CONVERT_PATCH, new=AsyncMock(return_value=(b"fake-pdf", None))):
                with patch(_DRIVE_PATCH, new=AsyncMock(return_value=("fid123", "https://drive.google.com/file/fid123/view", None))):
                    result = await generate_resume(job_id=1, current_user=_make_user(), db=db)

    body = result.body  # JSONResponse
    data = json.loads(body)
    assert data["job_posting_id"] == 1
    assert data["resume"]["name"] == "Jane Doe"
    assert data["resume"]["headline"] == "Senior Data Engineer tailored for Fintech"
    assert data["drive_file_id"] == "fid123"
    assert data["drive_link"] == "https://drive.google.com/file/fid123/view"


@pytest.mark.asyncio
async def test_generate_resume_upserts_to_db():
    from app.modules.agents.router import generate_resume

    db = _make_db()

    with patch(_AGENT_PATCH, new=AsyncMock(return_value=(_make_resume_output(), {}))):
        with patch(_DOCX_PATCH, return_value=b"fake-docx"):
            with patch(_CONVERT_PATCH, new=AsyncMock(return_value=(b"fake-pdf", None))):
                with patch(_DRIVE_PATCH, new=AsyncMock(return_value=("fid", "https://link", None))):
                    await generate_resume(job_id=1, current_user=_make_user(), db=db)

    # 2 commits: one after insert, one after drive update
    assert db.commit.await_count == 2
    # 7 executes: job + profile + drive_token + app_link + insert + drive_file_id + update
    assert db.execute.await_count == 7


@pytest.mark.asyncio
async def test_generate_resume_404_when_job_not_found():
    from fastapi import HTTPException
    from app.modules.agents.router import generate_resume

    db = _make_db(has_job=False)

    with pytest.raises(HTTPException) as exc_info:
        await generate_resume(job_id=999, current_user=_make_user(), db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_generate_resume_422_when_no_resume_in_profile():
    from fastapi import HTTPException
    from app.modules.agents.router import generate_resume

    db = _make_db(resume_text="")

    with pytest.raises(HTTPException) as exc_info:
        await generate_resume(job_id=1, current_user=_make_user(), db=db)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_generate_resume_422_when_drive_not_connected():
    from fastapi import HTTPException
    from app.modules.agents.router import generate_resume

    db = _make_db(drive_connected=False)

    with pytest.raises(HTTPException) as exc_info:
        await generate_resume(job_id=1, current_user=_make_user(), db=db)

    assert exc_info.value.status_code == 422
    assert "Google Drive not connected" in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_resume_207_when_drive_upload_fails():
    """When Drive upload raises an exception, endpoint returns 207 with drive_error."""
    from app.modules.agents.router import generate_resume

    db = _make_db()

    with patch(_AGENT_PATCH, new=AsyncMock(return_value=(_make_resume_output(), {}))):
        with patch(_DOCX_PATCH, return_value=b"fake-docx"):
            with patch(_CONVERT_PATCH, new=AsyncMock(side_effect=Exception("Drive quota exceeded"))):
                result = await generate_resume(job_id=1, current_user=_make_user(), db=db)

    assert result.status_code == 207
    data = json.loads(result.body)
    assert "drive_error" in data
    assert "Drive quota exceeded" in data["drive_error"]
    assert data["resume"]["name"] == "Jane Doe"
    # resume_json kept in DB: only 1 commit (the INSERT), not 2
    assert db.commit.await_count == 1


@pytest.mark.asyncio
async def test_generate_resume_201_on_success():
    """Successful generation + upload returns 201."""
    from app.modules.agents.router import generate_resume

    db = _make_db()

    with patch(_AGENT_PATCH, new=AsyncMock(return_value=(_make_resume_output(), {}))):
        with patch(_DOCX_PATCH, return_value=b"fake-docx"):
            with patch(_CONVERT_PATCH, new=AsyncMock(return_value=(b"fake-pdf", None))):
                with patch(_DRIVE_PATCH, new=AsyncMock(return_value=("fid", "https://link", None))):
                    result = await generate_resume(job_id=1, current_user=_make_user(), db=db)

    assert result.status_code == 201
    data = json.loads(result.body)
    assert "drive_error" not in data
    assert data["drive_file_id"] == "fid"


@pytest.mark.asyncio
async def test_generate_resume_502_when_agent_returns_error():
    from fastapi import HTTPException
    from app.modules.agents.router import generate_resume

    db = _make_db()
    agent_error = AgentError(error="LLM timeout", raw_output=None)

    with patch(_AGENT_PATCH, new=AsyncMock(return_value=(agent_error, {}))):
        with patch(_DOCX_PATCH, return_value=b"fake-docx"):
            with patch(_CONVERT_PATCH, new=AsyncMock(return_value=(b"fake-pdf", None))):
                with patch(_DRIVE_PATCH, new=AsyncMock(return_value=("fid", "https://link", None))):
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
