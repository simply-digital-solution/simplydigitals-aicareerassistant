"""Tests for purge_stale_research_jobs.

Execute call sequence when candidates are found:
  [0] candidate SELECT
  [1] DELETE FROM user_job_postings WHERE job_posting_id IN (...)
  [2] DELETE FROM job_postings WHERE id IN (...)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta, timezone


def _make_db_with_candidates(ids: list[int]):
    """DB mock returning the given IDs from the candidate SELECT."""
    candidate_result = MagicMock()
    candidate_result.fetchall.return_value = [(i,) for i in ids]
    delete_result = MagicMock()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[candidate_result, delete_result, delete_result])
    db.commit = AsyncMock()
    return db


def _make_db_empty():
    """DB mock returning no candidates."""
    empty_result = MagicMock()
    empty_result.fetchall.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=empty_result)
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# No stale jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_zero_when_no_candidates():
    from app.pipeline.job_cleanup import purge_stale_research_jobs

    db = _make_db_empty()
    deleted = await purge_stale_research_jobs(db, days=30)

    assert deleted == 0
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Deletes stale research-only jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deletes_stale_jobs_and_returns_count():
    from app.pipeline.job_cleanup import purge_stale_research_jobs

    db = _make_db_with_candidates([1, 2, 3])
    deleted = await purge_stale_research_jobs(db, days=30)

    assert deleted == 3
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# user_job_postings deleted before job_postings (FK order)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_job_postings_deleted_before_job_postings():
    from app.pipeline.job_cleanup import purge_stale_research_jobs

    db = _make_db_with_candidates([10, 20])
    await purge_stale_research_jobs(db, days=30)

    # [1] must be the ujp DELETE, [2] must be the jp DELETE
    ujp_sql = str(db.execute.call_args_list[1][0][0])
    jp_sql  = str(db.execute.call_args_list[2][0][0])
    assert "DELETE FROM user_job_postings" in ujp_sql
    assert "DELETE FROM job_postings" in jp_sql


# ---------------------------------------------------------------------------
# DELETE statements contain correct IDs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_statements_include_candidate_ids():
    from app.pipeline.job_cleanup import purge_stale_research_jobs

    db = _make_db_with_candidates([10, 20])
    await purge_stale_research_jobs(db, days=7)

    ujp_sql = str(db.execute.call_args_list[1][0][0])
    jp_sql  = str(db.execute.call_args_list[2][0][0])
    for sql in (ujp_sql, jp_sql):
        assert "10" in sql
        assert "20" in sql


# ---------------------------------------------------------------------------
# Protected statuses appear in SELECT query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_select_excludes_protected_statuses():
    from app.pipeline.job_cleanup import purge_stale_research_jobs, _PROTECTED_STATUSES

    db = _make_db_empty()
    await purge_stale_research_jobs(db, days=30)

    select_sql = str(db.execute.call_args_list[0][0][0])
    for status in _PROTECTED_STATUSES:
        assert status in select_sql


# ---------------------------------------------------------------------------
# generated_resumes protection appears in SELECT query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_select_excludes_jobs_with_generated_resumes():
    from app.pipeline.job_cleanup import purge_stale_research_jobs

    db = _make_db_empty()
    await purge_stale_research_jobs(db, days=30)

    select_sql = str(db.execute.call_args_list[0][0][0])
    assert "generated_resumes" in select_sql


# ---------------------------------------------------------------------------
# Custom days parameter reaches the query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_custom_days_used_in_cutoff():
    from app.pipeline.job_cleanup import purge_stale_research_jobs

    db = _make_db_empty()
    await purge_stale_research_jobs(db, days=7)

    params = db.execute.call_args_list[0][0][1]
    cutoff_dt = params["cutoff"]
    assert isinstance(cutoff_dt, datetime)
    expected = datetime.now(timezone.utc) - timedelta(days=7)
    assert abs((cutoff_dt - expected).total_seconds()) < 5


# ---------------------------------------------------------------------------
# Admin endpoint integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_cleanup_endpoint_returns_deleted_count():
    from app.main import app
    from app.shared.database import get_db
    from httpx import AsyncClient, ASGITransport

    candidate_result = MagicMock()
    candidate_result.fetchall.return_value = [(1,), (2,)]
    delete_result = MagicMock()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[candidate_result, delete_result, delete_result])
    mock_db.commit = AsyncMock()

    async def _override():
        yield mock_db

    app.dependency_overrides[get_db] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/cleanup/research-jobs?days=30",
                headers={"X-User-Email": "pandiri.vasu@simplydigitals.com.sg"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] == 2
        assert body["older_than_days"] == 30
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_admin_cleanup_endpoint_rejects_non_admin():
    from app.main import app
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/admin/cleanup/research-jobs",
            headers={"X-User-Email": "other@example.com"},
        )
    assert resp.status_code == 403
