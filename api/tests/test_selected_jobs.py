"""
Tests for the Selected Jobs feature:
  - GET /research/jobs/selected
  - POST /applications/ stores job_posting_id
  - GET /research/jobs excludes selected jobs
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_user(user_id: int = 1):
    user = MagicMock()
    user.id = user_id
    return user


# ---------------------------------------------------------------------------
# GET /research/jobs/selected
# ---------------------------------------------------------------------------

def _db_selected(rows=None):
    db = AsyncMock()
    result = MagicMock()
    result.mappings.return_value = rows or []
    db.execute.return_value = result
    return db


def _make_job_row(**overrides):
    row = {
        "id": 1, "mcf_uuid": "abc", "title": "Data Engineer", "company": "ACME",
        "url": "https://mcf.sg/job/abc", "location": "Singapore",
        "inferred_industries": '["Technology & Software"]',
        "posted_at": "2026-06-10T10:00:00Z", "scraped_at": "2026-06-11T07:00:00Z",
        "scored": 1, "fit_score": 0.82, "reasons": '["Good match"]', "risks": '["None"]',
        "key_keywords": '["Python"]', "scoring_breakdown": None,
        "score_error": None, "scored_at": "2026-06-11T08:00:00Z",
        "archived": 0, "application_id": 10,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_get_selected_jobs_returns_jobs():
    from app.modules.agents.router import get_selected_jobs
    db = _db_selected([_make_job_row()])
    result = await get_selected_jobs(current_user=_make_user(), db=db)
    assert result["total"] == 1
    assert result["jobs"][0]["title"] == "Data Engineer"


@pytest.mark.asyncio
async def test_get_selected_jobs_empty_when_none_selected():
    from app.modules.agents.router import get_selected_jobs
    db = _db_selected([])
    result = await get_selected_jobs(current_user=_make_user(), db=db)
    assert result["total"] == 0
    assert result["jobs"] == []


@pytest.mark.asyncio
async def test_get_selected_jobs_query_filters_by_user():
    from app.modules.agents.router import get_selected_jobs
    db = _db_selected([])
    await get_selected_jobs(current_user=_make_user(user_id=42), db=db)
    sql = db.execute.call_args.args[0].text
    params = db.execute.call_args.args[1]
    assert "user_id" in sql or "uid" in sql
    assert params["uid"] == 42


@pytest.mark.asyncio
async def test_get_selected_jobs_filters_by_selected_status():
    from app.modules.agents.router import get_selected_jobs
    db = _db_selected([])
    await get_selected_jobs(current_user=_make_user(), db=db)
    sql = db.execute.call_args.args[0].text
    assert "selected" in sql


@pytest.mark.asyncio
async def test_get_selected_jobs_joins_on_job_posting_id():
    from app.modules.agents.router import get_selected_jobs
    db = _db_selected([])
    await get_selected_jobs(current_user=_make_user(), db=db)
    sql = db.execute.call_args.args[0].text
    assert "job_posting_id" in sql


# ---------------------------------------------------------------------------
# POST /applications/ stores job_posting_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_application_stores_job_posting_id():
    from app.modules.applications.schemas import ApplicationCreate
    body = ApplicationCreate(
        company_name="ACME",
        role_title="Data Engineer",
        source_url="https://mcf.sg/job/abc",
        job_posting_id=42,
    )
    assert body.job_posting_id == 42


@pytest.mark.asyncio
async def test_create_application_job_posting_id_optional():
    from app.modules.applications.schemas import ApplicationCreate
    body = ApplicationCreate(company_name="ACME", role_title="Data Engineer")
    assert body.job_posting_id is None


# ---------------------------------------------------------------------------
# GET /research/jobs excludes jobs with any application row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_stored_jobs_excludes_any_application():
    from app.modules.agents.router import get_stored_jobs
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    jobs_result = MagicMock()
    jobs_result.mappings.return_value = []

    db = AsyncMock()
    db.execute.side_effect = [count_result, jobs_result]

    await get_stored_jobs(page=1, per_page=10, role="", days=0,
                          current_user=_make_user(), db=db)

    where_sql = db.execute.call_args_list[0].args[0].text
    assert "NOT IN" in where_sql
    assert "job_posting_id" in where_sql
    assert "selected" not in where_sql


# GET /research/jobs min_score filter excludes unscored jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_stored_jobs_min_score_excludes_unscored():
    from app.modules.agents.router import get_stored_jobs
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    jobs_result = MagicMock()
    jobs_result.mappings.return_value = []

    db = AsyncMock()
    db.execute.side_effect = [count_result, jobs_result]

    await get_stored_jobs(page=1, per_page=10, role="", days=0, min_score=0.8,
                          current_user=_make_user(), db=db)

    where_sql = db.execute.call_args_list[0].args[0].text
    assert "fit_score >= :min_score" in where_sql
    assert "scored = 0" not in where_sql
