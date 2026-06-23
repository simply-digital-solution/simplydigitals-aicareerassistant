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
    row = MagicMock()
    row.__getitem__ = lambda self, i: [1, "", None, "Corp"][i]

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
