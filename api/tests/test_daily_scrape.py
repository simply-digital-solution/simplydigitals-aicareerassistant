"""
Unit tests for api/app/pipeline/daily_scrape.py

All external calls (MCF scraper, DB) are mocked so tests run without a live
database or network connection.

Per-job execute() call sequence (after profile select):
  1. INSERT ... ON CONFLICT DO UPDATE ... → .rowcount (0 = dup unchanged, 1 = inserted/updated)
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
    p.target_titles     = json.dumps(target_titles)     if target_titles     is not None else None
    p.target_industries = json.dumps(target_industries) if target_industries is not None else None
    return p


def _profile_exec(profile):
    m = MagicMock()
    m.scalar_one_or_none.return_value = profile
    return m


def _upsert_exec(rowcount=1):
    """Simulates the upsert INSERT ... ON CONFLICT DO UPDATE."""
    m = MagicMock()
    m.rowcount = rowcount
    return m


def _make_job(url="https://www.mycareersfuture.gov.sg/job/abc123",
              title="Data Engineer", company="ACME",
              inferred_industries=None, posted_at=None,
              mcf_uuid="abc123uuid"):
    return {
        "url":                 url,
        "title":               title,
        "company":             company,
        "location":            "Singapore",
        "description":         "Build data pipelines",
        "inferred_industries": inferred_industries or [],
        "posted_at":           posted_at,
        "mcf_uuid":            mcf_uuid,
    }


# ---------------------------------------------------------------------------
# scrape_for_user — no profile
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_profile_returns_zero():
    db = AsyncMock()
    db.execute.return_value = _profile_exec(None)

    inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 0


# ---------------------------------------------------------------------------
# scrape_for_user — no target titles
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_target_titles_returns_zero():
    db = AsyncMock()
    db.execute.return_value = _profile_exec(_make_profile(target_titles=[]))

    inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 0


# ---------------------------------------------------------------------------
# scrape_for_user — happy path: no duplicate, job inserted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inserts_new_job():
    profile = _make_profile(target_titles=["Data Engineer"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),  # SELECT profile
        _upsert_exec(1),          # INSERT ON CONFLICT → 1 row inserted
    ]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture",
               AsyncMock(return_value=[_make_job()])):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 1
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# scrape_for_user — same mcf_uuid → upsert updates industries, rowcount=0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_day_duplicate_is_skipped():
    profile = _make_profile(target_titles=["Data Engineer"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),  # SELECT profile
        _upsert_exec(0),          # ON CONFLICT → same industries, nothing changed
    ]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture",
               AsyncMock(return_value=[_make_job(posted_at="2026-06-14T10:00:00Z")])):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 0
    assert db.execute.call_count == 2


# ---------------------------------------------------------------------------
# scrape_for_user — existing job with changed industries → upsert updates it
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_different_date_not_duplicate():
    profile = _make_profile(target_titles=["Data Engineer"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),  # SELECT profile
        _upsert_exec(1),          # INSERT ON CONFLICT → inserted or updated
    ]

    job = _make_job(posted_at="2026-06-15T10:00:00Z", mcf_uuid="newuuid456")

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture",
               AsyncMock(return_value=[job])):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 1


# ---------------------------------------------------------------------------
# scrape_for_user — MCF raises → gracefully continues, returns 0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scraper_error_is_handled():
    profile = _make_profile(target_titles=["SRE"], target_industries=[])
    db = AsyncMock()
    db.execute.return_value = _profile_exec(profile)

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
    db.execute.return_value = _profile_exec(profile)

    job = _make_job(inferred_industries=["Healthcare & Life Sciences"])

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[job])):
        inserted = await scrape_for_user(user_id=1, db=db)

    # Filtered before dedup check — only 1 execute call (profile select)
    assert inserted == 0
    assert db.execute.call_count == 1


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
    db.execute.side_effect = [
        _profile_exec(profile),
        _upsert_exec(1),
    ]

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
    db.execute.return_value = _profile_exec(profile)

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture",
               AsyncMock(return_value=[_make_job(url="")])):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 0
    assert db.execute.call_count == 1  # only profile select


# ---------------------------------------------------------------------------
# scrape_for_all_users — iterates all user IDs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_for_all_users_calls_each_user():
    db = AsyncMock()
    users_exec = MagicMock()
    users_exec.fetchall.return_value = [(1,), (2,)]
    db.execute.return_value = users_exec

    with patch("app.pipeline.daily_scrape.scrape_for_user",
               AsyncMock(return_value=5)) as mock_scrape:
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
