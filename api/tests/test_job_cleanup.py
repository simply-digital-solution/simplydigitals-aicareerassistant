"""Tests for purge_stale_research_jobs."""
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch
from datetime import datetime, timedelta, timezone


def _make_db(fetchall_return=None, rowcount=0):
    mock_result = MagicMock()
    mock_result.fetchall.return_value = fetchall_return or []
    mock_result.rowcount = rowcount

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# No stale jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_zero_when_no_candidates():
    from app.pipeline.job_cleanup import purge_stale_research_jobs

    db = _make_db(fetchall_return=[])
    deleted = await purge_stale_research_jobs(db, days=30)

    assert deleted == 0
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Deletes stale research-only jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deletes_stale_jobs_and_returns_count():
    from app.pipeline.job_cleanup import purge_stale_research_jobs

    # First execute call returns candidate IDs
    candidate_result = MagicMock()
    candidate_result.fetchall.return_value = [(1,), (2,), (3,)]

    delete_result = MagicMock()
    delete_result.fetchall.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[candidate_result, delete_result])
    db.commit = AsyncMock()

    deleted = await purge_stale_research_jobs(db, days=30)

    assert deleted == 3
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# DELETE statement contains correct IDs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_statement_includes_candidate_ids():
    from app.pipeline.job_cleanup import purge_stale_research_jobs

    candidate_result = MagicMock()
    candidate_result.fetchall.return_value = [(10,), (20,)]

    delete_result = MagicMock()
    delete_result.fetchall.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[candidate_result, delete_result])
    db.commit = AsyncMock()

    await purge_stale_research_jobs(db, days=7)

    # Second call is the DELETE
    delete_call = db.execute.call_args_list[1]
    sql = str(delete_call[0][0])
    assert "10" in sql
    assert "20" in sql
    assert "DELETE FROM job_postings" in sql


# ---------------------------------------------------------------------------
# Protected statuses appear in SELECT query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_select_excludes_protected_statuses():
    from app.pipeline.job_cleanup import purge_stale_research_jobs, _PROTECTED_STATUSES

    candidate_result = MagicMock()
    candidate_result.fetchall.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=candidate_result)
    db.commit = AsyncMock()

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

    candidate_result = MagicMock()
    candidate_result.fetchall.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=candidate_result)
    db.commit = AsyncMock()

    await purge_stale_research_jobs(db, days=30)

    select_sql = str(db.execute.call_args_list[0][0][0])
    assert "generated_resumes" in select_sql


# ---------------------------------------------------------------------------
# Custom days parameter reaches the query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_custom_days_used_in_cutoff():
    from app.pipeline.job_cleanup import purge_stale_research_jobs
    from datetime import datetime, timezone, timedelta

    candidate_result = MagicMock()
    candidate_result.fetchall.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=candidate_result)
    db.commit = AsyncMock()

    await purge_stale_research_jobs(db, days=7)

    _, kwargs = db.execute.call_args_list[0]
    params = db.execute.call_args_list[0][0][1]
    cutoff_str = params["cutoff"]
    cutoff_dt = datetime.fromisoformat(cutoff_str)
    expected = datetime.now(timezone.utc) - timedelta(days=7)
    # Allow 5s tolerance for test execution time
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
    delete_result.fetchall.return_value = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[candidate_result, delete_result])
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
