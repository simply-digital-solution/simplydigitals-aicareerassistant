"""
Unit tests for archive_old_job_postings() in job_cleanup.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_db(rowcount: int = 0):
    result = MagicMock()
    result.rowcount = rowcount
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Returns the number of archived rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_archived_count():
    from app.pipeline.job_cleanup import archive_old_job_postings
    db = _make_db(rowcount=7)
    assert await archive_old_job_postings(db, days=14) == 7


@pytest.mark.asyncio
async def test_returns_zero_when_nothing_archived():
    from app.pipeline.job_cleanup import archive_old_job_postings
    db = _make_db(rowcount=0)
    assert await archive_old_job_postings(db, days=14) == 0


# ---------------------------------------------------------------------------
# SQL shape — UPDATE targets user_job_postings, not job_postings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_updates_user_job_postings_not_job_postings():
    from app.pipeline.job_cleanup import archive_old_job_postings
    db = _make_db()
    await archive_old_job_postings(db, days=14)
    sql = db.execute.call_args[0][0].text
    assert "UPDATE user_job_postings" in sql
    assert "archived = true" in sql


@pytest.mark.asyncio
async def test_only_touches_unarchived_rows():
    from app.pipeline.job_cleanup import archive_old_job_postings
    db = _make_db()
    await archive_old_job_postings(db, days=14)
    sql = db.execute.call_args[0][0].text
    assert "archived = false" in sql


@pytest.mark.asyncio
async def test_filters_by_posted_at_not_scraped_at():
    from app.pipeline.job_cleanup import archive_old_job_postings
    db = _make_db()
    await archive_old_job_postings(db, days=14)
    sql = db.execute.call_args[0][0].text
    assert "posted_at" in sql
    assert "scraped_at" not in sql


# ---------------------------------------------------------------------------
# Application guard — jobs with any application are never auto-archived
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_excludes_jobs_with_applications():
    from app.pipeline.job_cleanup import archive_old_job_postings
    db = _make_db()
    await archive_old_job_postings(db, days=14)
    sql = db.execute.call_args[0][0].text
    assert "applications" in sql
    assert "NOT EXISTS" in sql


# ---------------------------------------------------------------------------
# Cutoff uses the days parameter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cutoff_uses_days_parameter():
    from app.pipeline.job_cleanup import archive_old_job_postings
    from datetime import datetime, timezone, timedelta
    db = _make_db()
    await archive_old_job_postings(db, days=7)
    params = db.execute.call_args[0][1]
    assert "cutoff" in params
    expected = datetime.now(timezone.utc) - timedelta(days=7)
    assert abs((params["cutoff"] - expected).total_seconds()) < 5


@pytest.mark.asyncio
async def test_default_days_is_14():
    from app.pipeline.job_cleanup import archive_old_job_postings, ARCHIVE_POSTING_DAYS
    from datetime import datetime, timezone, timedelta
    assert ARCHIVE_POSTING_DAYS == 14
    db = _make_db()
    await archive_old_job_postings(db)
    params = db.execute.call_args[0][1]
    expected = datetime.now(timezone.utc) - timedelta(days=14)
    assert abs((params["cutoff"] - expected).total_seconds()) < 5


# ---------------------------------------------------------------------------
# Always commits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_commits_even_when_zero_rows():
    from app.pipeline.job_cleanup import archive_old_job_postings
    db = _make_db(rowcount=0)
    await archive_old_job_postings(db, days=14)
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Admin endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_archive_endpoint_returns_count():
    from app.main import app
    from app.shared.database import get_db
    from httpx import AsyncClient, ASGITransport

    result = MagicMock()
    result.rowcount = 5
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=result)
    mock_db.commit = AsyncMock()

    async def _override():
        yield mock_db

    app.dependency_overrides[get_db] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/cleanup/archive-old-jobs?days=14",
                headers={"X-User-Email": "pandiri.vasu@simplydigitals.com.sg"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["archived"] == 5
        assert body["older_than_days"] == 14
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_admin_archive_endpoint_rejects_non_admin():
    from app.main import app
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/admin/cleanup/archive-old-jobs",
            headers={"X-User-Email": "other@example.com"},
        )
    assert resp.status_code == 403
