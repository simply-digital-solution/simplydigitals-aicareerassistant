"""Tests for interview-related endpoints:
- GET /research/jobs/interviewing
- POST /agents/interview-from-job
- GET /agents/interview-pack/{application_id}
- Admin email set: both addresses allowed
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.shared.database import get_db
from app.modules.auth.router import get_current_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_user(user_id: int = 1, email: str = "test@example.com"):
    user = MagicMock()
    user.id = user_id
    user.email = email
    return user


def _db_returning(rows, rowcount: int = 0):
    mock_result = MagicMock()
    mock_result.mappings.return_value = [dict(r) for r in rows]
    mock_result.first.return_value = rows[0] if rows else None
    mock_result.rowcount = rowcount

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    async def _override():
        yield mock_db

    return _override


@pytest.fixture
def app():
    from app.main import app as fastapi_app
    return fastapi_app


# ---------------------------------------------------------------------------
# GET /research/jobs/interviewing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_interviewing_jobs_returns_empty(app):
    user = _mock_user()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_returning([])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/research/jobs/interviewing",
                headers={"X-User-Email": "test@example.com"},
            )
        assert r.status_code == 200
        assert r.json() == {"total": 0, "jobs": []}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_interviewing_jobs_returns_jobs(app):
    job_row = {
        "id": 1, "mcf_uuid": "abc", "title": "SWE", "company": "Corp",
        "url": "https://example.com", "location": "SG",
        "inferred_industries": '["Tech"]', "posted_at": None, "scraped_at": "2026-06-01",
        "scored": True, "fit_score": 0.8, "reasons": "[]", "risks": "[]",
        "key_keywords": "[]", "scoring_breakdown": None, "recommendation": None,
        "score_error": None, "scored_at": None, "scored_by_model": None, "archived": False,
        "application_id": 10, "application_status": "interviewing", "applied_at": None,
        "has_interview_pack": False,
    }
    user = _mock_user()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_returning([job_row])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/research/jobs/interviewing",
                headers={"X-User-Email": "test@example.com"},
            )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["jobs"][0]["title"] == "SWE"
        assert data["jobs"][0]["application_status"] == "interviewing"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /agents/interview-pack/{application_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_interview_pack_not_found(app):
    user = _mock_user()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_returning([])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/agents/interview-pack/99",
                headers={"X-User-Email": "test@example.com"},
            )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_interview_pack_returns_pack(app):
    from datetime import datetime, timezone
    pack_row = MagicMock()
    pack_row.__getitem__ = lambda self, i: [
        "My pitch text",
        json.dumps([{"q": "Q1", "situation": "S", "task": "T", "action": "A", "result": "R"}]),
        datetime(2026, 6, 23, 10, 0, 0, tzinfo=timezone.utc),
    ][i]

    mock_result = MagicMock()
    mock_result.first.return_value = pack_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    async def _db_override():
        yield mock_db

    user = _mock_user()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/agents/interview-pack/10",
                headers={"X-User-Email": "test@example.com"},
            )
        assert r.status_code == 200
        data = r.json()
        assert data["pitch"] == "My pitch text"
        assert len(data["star_questions"]) == 1
        assert data["star_questions"][0]["q"] == "Q1"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /agents/interview-from-job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interview_from_job_not_found(app):
    user = _mock_user()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_returning([])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/agents/interview-from-job",
                json={"application_id": 99},
                headers={"X-User-Email": "test@example.com"},
            )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_interview_from_job_no_jd_returns_422(app):
    # Row has 6 elements: id, job_description, jd_summary, company, job_posting_id, posting_description
    row = MagicMock()
    row.__getitem__ = lambda self, i: [1, "", None, "Corp", None, ""][i]

    mock_result = MagicMock()
    mock_result.first.return_value = row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    async def _db_override():
        yield mock_db

    user = _mock_user()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/agents/interview-from-job",
                json={"application_id": 1},
                headers={"X-User-Email": "test@example.com"},
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# _flatten_resume_json helper
# ---------------------------------------------------------------------------

def test_flatten_resume_json_returns_plain_text():
    import json
    from app.modules.agents.router import _flatten_resume_json

    resume = {
        "name": "Jane Doe",
        "headline": "Senior Data Engineer",
        "sections": [
            {
                "section_type": "summary",
                "title": "Professional Summary",
                "content": ["Experienced data engineer with 8 years in fintech."],
                "experience": [],
            },
            {
                "section_type": "experience",
                "title": "Work Experience",
                "content": [],
                "experience": [
                    {
                        "title": "Data Engineer",
                        "company": "ACME Corp",
                        "dates": "Jan 2020 – Present",
                        "summary": "Led data platform delivery.",
                        "bullets": ["Built pipelines", "Reduced latency by 40%"],
                    }
                ],
            },
        ],
    }
    text = _flatten_resume_json(json.dumps(resume))
    assert "Jane Doe" in text
    assert "Senior Data Engineer" in text
    assert "Experienced data engineer" in text
    assert "ACME Corp" in text
    assert "• Built pipelines" in text
    assert "• Reduced latency by 40%" in text


def test_flatten_resume_json_handles_invalid_json():
    from app.modules.agents.router import _flatten_resume_json

    assert _flatten_resume_json("not-json") == ""
    assert _flatten_resume_json("") == ""


def test_flatten_resume_json_handles_empty_sections():
    import json
    from app.modules.agents.router import _flatten_resume_json

    resume = {"name": "John", "headline": "Engineer", "sections": []}
    text = _flatten_resume_json(json.dumps(resume))
    assert "John" in text
    assert "Engineer" in text


# ---------------------------------------------------------------------------
# interview_pack_agent — _build_user_message
# ---------------------------------------------------------------------------

def test_build_user_message_includes_tailored_resume():
    from app.modules.agents.interview_pack_agent import _build_user_message

    profile = {"background": {"current_title": "PM", "years_experience": 5, "skills": [], "education": "", "experience_summary": ""}, "targets": {"roles": []}}
    msg = _build_user_message(profile, "Some JD", "ACME", None, tailored_resume_text="My tailored resume content")
    assert "TAILORED RESUME SENT TO THIS EMPLOYER" in msg
    assert "My tailored resume content" in msg
    assert "END RESUME" in msg


def test_build_user_message_omits_resume_block_when_empty():
    from app.modules.agents.interview_pack_agent import _build_user_message

    profile = {"background": {"current_title": "PM", "years_experience": 5, "skills": [], "education": "", "experience_summary": ""}, "targets": {"roles": []}}
    msg = _build_user_message(profile, "Some JD", "ACME", None, tailored_resume_text="")
    assert "TAILORED RESUME" not in msg
    assert "TARGET JOB DESCRIPTION" in msg


def test_build_user_message_uses_jd_summary_over_full_jd():
    from app.modules.agents.interview_pack_agent import _build_user_message

    profile = {"background": {"current_title": "PM", "years_experience": 5, "skills": [], "education": "", "experience_summary": ""}, "targets": {"roles": []}}
    msg = _build_user_message(profile, "FULL JD TEXT", "ACME", jd_summary="SHORT SUMMARY", tailored_resume_text="")
    assert "SHORT SUMMARY" in msg
    assert "FULL JD TEXT" not in msg


def test_build_user_message_falls_back_to_jd_when_no_summary():
    from app.modules.agents.interview_pack_agent import _build_user_message

    profile = {"background": {"current_title": "PM", "years_experience": 5, "skills": [], "education": "", "experience_summary": ""}, "targets": {"roles": []}}
    msg = _build_user_message(profile, "FULL JD TEXT", "ACME", jd_summary=None, tailored_resume_text="")
    assert "FULL JD TEXT" in msg


# ---------------------------------------------------------------------------
# interview_pack_agent — run_interview_pack_agent
# ---------------------------------------------------------------------------

_AGENT_CLIENT_PATCH = "app.modules.agents.interview_pack_agent.get_llm_client"


@pytest.mark.asyncio
async def test_run_interview_pack_agent_upserts_on_success():
    from app.modules.agents.interview_pack_agent import run_interview_pack_agent
    from app.shared.schemas import InterviewPackOutput, StarQuestion

    pack = InterviewPackOutput(
        pitch="My pitch",
        star_questions=[StarQuestion(q="Q1", situation="S", task="T", action="A", result="R")],
    )
    mock_client = MagicMock()
    mock_client.run_agent = AsyncMock(return_value=(pack, {}))
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    with patch(_AGENT_CLIENT_PATCH, return_value=mock_client):
        result, _ = await run_interview_pack_agent(
            profile={}, jd_text="JD", db=db, user_id=1, application_id=5,
        )

    assert isinstance(result, InterviewPackOutput)
    assert result.pitch == "My pitch"
    db.execute.assert_awaited_once()  # upsert
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_interview_pack_agent_skips_db_on_agent_error():
    from app.modules.agents.interview_pack_agent import run_interview_pack_agent
    from app.shared.schemas import AgentError

    error = AgentError(error="LLM failed", raw_output=None)
    mock_client = MagicMock()
    mock_client.run_agent = AsyncMock(return_value=(error, {}))
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    with patch(_AGENT_CLIENT_PATCH, return_value=mock_client):
        result, _ = await run_interview_pack_agent(
            profile={}, jd_text="JD", db=db, user_id=1, application_id=5,
        )

    assert isinstance(result, AgentError)
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# interview_pack_docx — build_interview_pack_docx
# ---------------------------------------------------------------------------

def test_build_interview_pack_docx_returns_bytes():
    from app.shared.interview_pack_docx import build_interview_pack_docx
    from app.shared.schemas import InterviewPackOutput, StarQuestion

    pack = InterviewPackOutput(
        pitch="Hello, I am a PM with 5 years of experience.",
        star_questions=[
            StarQuestion(q="Tell me about a challenge.", situation="S", task="T", action="A", result="R"),
        ],
    )
    result = build_interview_pack_docx(pack, "ACME Corp", "Product Manager")
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_build_interview_pack_docx_is_valid_docx():
    from io import BytesIO
    from docx import Document
    from app.shared.interview_pack_docx import build_interview_pack_docx
    from app.shared.schemas import InterviewPackOutput, StarQuestion

    pack = InterviewPackOutput(
        pitch="Pitch text here.",
        star_questions=[
            StarQuestion(q="Q1", situation="S1", task="T1", action="A1", result="R1"),
            StarQuestion(q="Q2", situation="S2", task="T2", action="A2", result="R2"),
        ],
    )
    docx_bytes = build_interview_pack_docx(pack, "Beta Ltd", "Engineer")
    doc = Document(BytesIO(docx_bytes))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Beta Ltd" in full_text
    assert "Pitch text here." in full_text
    assert "Q1" in full_text
    assert "Q2" in full_text
    assert "S1" in full_text


# ---------------------------------------------------------------------------
# POST /agents/interview-from-job — Drive upload paths
# ---------------------------------------------------------------------------

def _make_app_row(jd="Some JD text", company="Corp", job_posting_id=42, posting_description=""):
    row = MagicMock()
    row.first.return_value = MagicMock(__getitem__=lambda self, i: [1, jd, None, company, job_posting_id, posting_description][i])
    return row


def _make_prof_row(connected: bool):
    row = MagicMock()
    row.__getitem__ = lambda self, k: {
        "google_access_token": "at123" if connected else None,
        "google_refresh_token": "rt123" if connected else None,
        "google_token_expiry": "2099-01-01T00:00:00Z" if connected else None,
    }[k]
    return row


def _make_pack_result():
    from app.shared.schemas import InterviewPackOutput, StarQuestion
    return InterviewPackOutput(
        pitch="My pitch",
        star_questions=[StarQuestion(q="Q1", situation="S", task="T", action="A", result="R")],
    )


_PACK_AGENT_PATCH = "app.modules.agents.router.run_interview_pack_agent"
_DOCX_PATCH = "app.shared.interview_pack_docx.build_interview_pack_docx"
_CONVERT_PATCH = "app.shared.google_drive.convert_docx_to_pdf_bytes"
_UPLOAD_PATCH = "app.shared.google_drive.upload_or_update_file"


@pytest.mark.asyncio
async def test_interview_from_job_drive_connected_returns_drive_fields(app):
    user = _mock_user()

    prof_result = MagicMock()
    prof_result.mappings.return_value.first.return_value = _make_prof_row(connected=True)

    gr_result = MagicMock()
    gr_result.first.return_value = None  # no tailored resume

    jp_result = MagicMock()
    jp_result.first.return_value = MagicMock(__getitem__=lambda self, i: "Product Manager")

    update_result = MagicMock()

    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[
        _make_app_row(),   # app lookup
        gr_result,         # tailored resume lookup
        profile_result,    # _load_profile
        prof_result,       # Drive token check
        jp_result,         # job title lookup
        update_result,     # UPDATE interview_packs
    ])
    mock_db.commit = AsyncMock()

    async def _db_override():
        yield mock_db

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override
    try:
        with patch(_PACK_AGENT_PATCH, new=AsyncMock(return_value=(_make_pack_result(), {}))):
            with patch(_DOCX_PATCH, return_value=b"docx"):
                with patch(_CONVERT_PATCH, new=AsyncMock(return_value=(b"pdf", None))):
                    with patch(_UPLOAD_PATCH, new=AsyncMock(return_value=("fid", "https://drive.link", None))):
                        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                            r = await client.post(
                                "/api/v1/agents/interview-from-job",
                                json={"application_id": 1},
                                headers={"X-User-Email": "test@example.com"},
                            )
        assert r.status_code == 200
        data = r.json()
        assert data["drive_file_id"] == "fid"
        assert data["drive_link"] == "https://drive.link"
        assert data["drive_error"] is None
        assert data["pitch"] == "My pitch"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_interview_from_job_drive_not_connected_returns_null_drive_fields(app):
    user = _mock_user()

    prof_result = MagicMock()
    prof_result.mappings.return_value.first.return_value = _make_prof_row(connected=False)

    gr_result = MagicMock()
    gr_result.first.return_value = None

    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[
        _make_app_row(),
        gr_result,
        profile_result,
        prof_result,
    ])
    mock_db.commit = AsyncMock()

    async def _db_override():
        yield mock_db

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override
    try:
        with patch(_PACK_AGENT_PATCH, new=AsyncMock(return_value=(_make_pack_result(), {}))):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    "/api/v1/agents/interview-from-job",
                    json={"application_id": 1},
                    headers={"X-User-Email": "test@example.com"},
                )
        assert r.status_code == 200
        data = r.json()
        assert data["drive_file_id"] is None
        assert data["drive_link"] is None
        assert data["drive_error"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_interview_from_job_drive_upload_failure_returns_drive_error(app):
    user = _mock_user()

    prof_result = MagicMock()
    prof_result.mappings.return_value.first.return_value = _make_prof_row(connected=True)

    gr_result = MagicMock()
    gr_result.first.return_value = None

    jp_result = MagicMock()
    jp_result.first.return_value = MagicMock(__getitem__=lambda self, i: "Engineer")

    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[
        _make_app_row(),
        gr_result,
        profile_result,
        prof_result,
        jp_result,
    ])
    mock_db.commit = AsyncMock()

    async def _db_override():
        yield mock_db

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override
    try:
        with patch(_PACK_AGENT_PATCH, new=AsyncMock(return_value=(_make_pack_result(), {}))):
            with patch(_DOCX_PATCH, return_value=b"docx"):
                with patch(_CONVERT_PATCH, new=AsyncMock(side_effect=Exception("Drive quota exceeded"))):
                    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                        r = await client.post(
                            "/api/v1/agents/interview-from-job",
                            json={"application_id": 1},
                            headers={"X-User-Email": "test@example.com"},
                        )
        assert r.status_code == 200
        data = r.json()
        assert data["drive_file_id"] is None
        assert "Drive quota exceeded" in data["drive_error"]
        # Pack content still returned even on Drive failure
        assert data["pitch"] == "My pitch"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_interview_from_job_agent_error_returns_500(app):
    from app.shared.schemas import AgentError

    user = _mock_user()

    gr_result = MagicMock()
    gr_result.first.return_value = None

    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[
        _make_app_row(),
        gr_result,
        profile_result,
    ])
    mock_db.commit = AsyncMock()

    async def _db_override():
        yield mock_db

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override
    try:
        with patch(_PACK_AGENT_PATCH, new=AsyncMock(return_value=(AgentError(error="LLM timeout", raw_output=None), {}))):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    "/api/v1/agents/interview-from-job",
                    json={"application_id": 1},
                    headers={"X-User-Email": "test@example.com"},
                )
        assert r.status_code == 500
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_interview_from_job_falls_back_to_posting_description_when_app_jd_null(app):
    """When applications.job_description is NULL, use job_postings.description instead."""
    user = _mock_user()

    prof_result = MagicMock()
    prof_result.mappings.return_value.first.return_value = _make_prof_row(connected=False)

    gr_result = MagicMock()
    gr_result.first.return_value = None

    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[
        # app_jd=None but posting_description has content
        _make_app_row(jd=None, posting_description="Scraped JD from job board"),
        gr_result,
        profile_result,
        prof_result,
    ])
    mock_db.commit = AsyncMock()

    async def _db_override():
        yield mock_db

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override
    try:
        with patch(_PACK_AGENT_PATCH, new=AsyncMock(return_value=(_make_pack_result(), {}))):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    "/api/v1/agents/interview-from-job",
                    json={"application_id": 1},
                    headers={"X-User-Email": "test@example.com"},
                )
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_interview_from_job_422_when_both_jd_sources_empty(app):
    """Returns 422 when both applications.job_description and job_postings.description are empty."""
    user = _mock_user()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_make_app_row(jd=None, posting_description="").first.return_value and
                                _make_app_row(jd=None, posting_description=""))
    mock_db.commit = AsyncMock()

    # Use the simpler approach — single execute returns the no-jd row
    row = MagicMock()
    row.first.return_value = MagicMock(__getitem__=lambda self, i: [1, None, None, "Corp", None, ""][i])
    mock_db.execute = AsyncMock(return_value=row)

    async def _db_override():
        yield mock_db

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/agents/interview-from-job",
                json={"application_id": 1},
                headers={"X-User-Email": "test@example.com"},
            )
        assert r.status_code == 422
        assert "job description" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_interview_from_job_fetches_tailored_resume_when_job_posting_exists(app):
    """Tailored resume is fetched and flattened when job_posting_id is set."""
    import json as _json
    user = _mock_user()

    resume_json = _json.dumps({
        "name": "Jane", "headline": "SWE", "sections": [
            {"section_type": "summary", "title": "Summary",
             "content": ["Expert Python developer"], "experience": []}
        ]
    })
    gr_row = MagicMock()
    gr_row.__getitem__ = lambda self, i: resume_json

    gr_result = MagicMock()
    gr_result.first.return_value = gr_row

    prof_result = MagicMock()
    prof_result.mappings.return_value.first.return_value = _make_prof_row(connected=False)

    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = None

    captured_kwargs: dict = {}

    async def _fake_agent(**kwargs):
        captured_kwargs.update(kwargs)
        return (_make_pack_result(), {})

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[
        _make_app_row(job_posting_id=42),
        gr_result,
        profile_result,
        prof_result,
    ])
    mock_db.commit = AsyncMock()

    async def _db_override():
        yield mock_db

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _db_override
    try:
        with patch(_PACK_AGENT_PATCH, new=AsyncMock(side_effect=_fake_agent)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post(
                    "/api/v1/agents/interview-from-job",
                    json={"application_id": 1},
                    headers={"X-User-Email": "test@example.com"},
                )
        assert "Expert Python developer" in captured_kwargs.get("tailored_resume_text", "")
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Admin: both email addresses accepted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_accepts_simplydigitals_email(app):
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def _db_override():
        yield mock_db

    app.dependency_overrides[get_db] = _db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/admin/stats/users-active",
                headers={"X-User-Email": "pandiri.vasu@simplydigitals.com.sg"},
            )
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_accepts_gmail(app):
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def _db_override():
        yield mock_db

    app.dependency_overrides[get_db] = _db_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/admin/stats/users-active",
                headers={"X-User-Email": "pandiri.vasu@gmail.com"},
            )
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_rejects_other_email(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/v1/admin/stats/users-active",
            headers={"X-User-Email": "hacker@evil.com"},
        )
    assert r.status_code == 403
