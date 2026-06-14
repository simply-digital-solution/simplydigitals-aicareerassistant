"""
Unit tests for api/app/pipeline/daily_scrape.py

All external calls (MCF scraper, DB) are mocked so tests run without a live
database or network connection.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.pipeline.daily_scrape import scrape_for_user, scrape_for_all_users


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(target_titles=None, target_industries=None):
    p = MagicMock()
    p.target_titles     = json.dumps(target_titles)    if target_titles    is not None else None
    p.target_industries = json.dumps(target_industries) if target_industries is not None else None
    return p


def _make_db(profile=None, rowcount=1):
    """Return a mock AsyncSession."""
    db = AsyncMock()

    # scalar_one_or_none() for profile select
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile

    # .execute() for the INSERT returns an object with .rowcount
    insert_result = MagicMock()
    insert_result.rowcount = rowcount

    # For scrape_for_all_users: SELECT user_id FROM profiles
    all_users_result = MagicMock()
    all_users_result.fetchall.return_value = []

    # Route execute calls: first call returns profile, subsequent ones return insert_result
    db.execute.side_effect = [profile_result, insert_result, insert_result, insert_result]
    return db


def _make_job(url="https://www.mycareersfuture.gov.sg/job/abc123",
              title="Data Engineer", company="ACME",
              inferred_industries=None, posted_at=None):
    return {
        "url": url,
        "title": title,
        "company": company,
        "location": "Singapore",
        "description": "Build data pipelines",
        "inferred_industries": inferred_industries or [],
        "posted_at": posted_at,
    }


# ---------------------------------------------------------------------------
# scrape_for_user — no profile
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_profile_returns_zero():
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock

    inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 0


# ---------------------------------------------------------------------------
# scrape_for_user — no target titles
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_target_titles_returns_zero():
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = _make_profile(target_titles=[])
    db.execute.return_value = result_mock

    inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 0


# ---------------------------------------------------------------------------
# scrape_for_user — happy path: one title, one job, no industry filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inserts_new_job():
    profile = _make_profile(target_titles=["Data Engineer"], target_industries=[])
    db      = AsyncMock()

    profile_exec = MagicMock()
    profile_exec.scalar_one_or_none.return_value = profile

    insert_exec = MagicMock()
    insert_exec.rowcount = 1

    db.execute.side_effect = [profile_exec, insert_exec]

    job = _make_job()

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[job])):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 1
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# scrape_for_user — duplicate job (rowcount=0 from INSERT OR IGNORE)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_job_not_counted():
    profile = _make_profile(target_titles=["Data Engineer"], target_industries=[])
    db      = AsyncMock()

    profile_exec = MagicMock()
    profile_exec.scalar_one_or_none.return_value = profile

    insert_exec = MagicMock()
    insert_exec.rowcount = 0   # row already existed → INSERT OR IGNORE → 0 rows affected

    db.execute.side_effect = [profile_exec, insert_exec]

    job = _make_job()

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[job])):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 0


# ---------------------------------------------------------------------------
# scrape_for_user — MCF raises → gracefully continues, returns 0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scraper_error_is_handled():
    profile = _make_profile(target_titles=["SRE"], target_industries=[])
    db      = AsyncMock()

    profile_exec = MagicMock()
    profile_exec.scalar_one_or_none.return_value = profile
    db.execute.return_value = profile_exec

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture",
               AsyncMock(side_effect=RuntimeError("network error"))):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 0


# ---------------------------------------------------------------------------
# scrape_for_user — industry filter drops a non-matching job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_industry_filter_drops_non_matching():
    profile = _make_profile(
        target_titles=["Software Engineer"],
        target_industries=["Banking & Financial Services"],
    )
    db = AsyncMock()
    profile_exec = MagicMock()
    profile_exec.scalar_one_or_none.return_value = profile
    db.execute.return_value = profile_exec

    job = _make_job(inferred_industries=["Healthcare & Life Sciences"])

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[job])):
        inserted = await scrape_for_user(user_id=1, db=db)

    # 0 because the job was filtered out before any INSERT
    assert inserted == 0


# ---------------------------------------------------------------------------
# scrape_for_user — industry filter passes matching job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_industry_filter_passes_matching():
    profile = _make_profile(
        target_titles=["Analyst"],
        target_industries=["Banking & Financial Services"],
    )
    db = AsyncMock()

    profile_exec = MagicMock()
    profile_exec.scalar_one_or_none.return_value = profile

    insert_exec = MagicMock()
    insert_exec.rowcount = 1

    db.execute.side_effect = [profile_exec, insert_exec]

    job = _make_job(inferred_industries=["Banking & Finance"])  # fuzzy match ≥0.80

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[job])):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 1


# ---------------------------------------------------------------------------
# scrape_for_user — job with missing URL is skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_with_empty_url_is_skipped():
    profile = _make_profile(target_titles=["DevOps"], target_industries=[])
    db = AsyncMock()

    profile_exec = MagicMock()
    profile_exec.scalar_one_or_none.return_value = profile
    db.execute.return_value = profile_exec

    job = _make_job(url="")  # no URL → can't extract UUID

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[job])):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 0


# ---------------------------------------------------------------------------
# scrape_for_all_users — iterates all user IDs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_for_all_users_calls_each_user():
    db = AsyncMock()

    users_exec = MagicMock()
    users_exec.fetchall.return_value = [(1,), (2,)]
    db.execute.return_value = users_exec

    with patch("app.pipeline.daily_scrape.scrape_for_user", AsyncMock(return_value=5)) as mock_scrape:
        await scrape_for_all_users(db)

    assert mock_scrape.call_count == 2
    mock_scrape.assert_any_call(1, db)
    mock_scrape.assert_any_call(2, db)


# ---------------------------------------------------------------------------
# scrape_for_all_users — one user fails, others still run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_for_all_users_continues_on_error():
    db = AsyncMock()

    users_exec = MagicMock()
    users_exec.fetchall.return_value = [(1,), (2,)]
    db.execute.return_value = users_exec

    call_count = 0

    async def _scrape(uid, _db):
        nonlocal call_count
        call_count += 1
        if uid == 1:
            raise RuntimeError("user 1 exploded")
        return 3

    with patch("app.pipeline.daily_scrape.scrape_for_user", _scrape):
        await scrape_for_all_users(db)

    assert call_count == 2
