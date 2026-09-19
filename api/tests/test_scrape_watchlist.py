"""
Unit tests for scrape_watchlist_for_user() in api/app/pipeline/daily_scrape.py

Per-company execute() call sequence (after profile select), one pair per
job returned by the platform scraper:
  1. INSERT INTO job_postings ... ON CONFLICT ... RETURNING id → .fetchone() returns (id,)
  2. INSERT INTO user_job_postings ... ON CONFLICT DO NOTHING RETURNING id → .fetchone() returns (id,) or None
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.pipeline.daily_scrape import scrape_watchlist_for_user


def _make_profile(watched_companies=None, target_titles=None):
    p = MagicMock()
    p.watched_companies = json.dumps(watched_companies) if watched_companies is not None else None
    p.target_titles = json.dumps(target_titles) if target_titles is not None else None
    return p


def _profile_exec(profile):
    m = MagicMock()
    m.scalar_one_or_none.return_value = profile
    return m


def _jp_insert_exec(job_id=42):
    m = MagicMock()
    m.fetchone.return_value = (job_id,)
    return m


def _ujp_insert_exec(inserted=True):
    m = MagicMock()
    m.fetchone.return_value = (1,) if inserted else None
    return m


def _make_scraped_job(url, title="Engineer", company="Acme"):
    return {
        "url": url,
        "title": title,
        "company": company,
        "location": "Singapore",
        "description": "Build things",
        "inferred_industries": [],
        "posted_at": None,
    }


# ---------------------------------------------------------------------------
# No profile / empty watchlist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_profile_returns_zero():
    db = AsyncMock()
    db.execute.return_value = _profile_exec(None)

    inserted = await scrape_watchlist_for_user(user_id=1, db=db)

    assert inserted == 0


@pytest.mark.asyncio
async def test_empty_watchlist_returns_zero():
    db = AsyncMock()
    db.execute.return_value = _profile_exec(_make_profile(watched_companies=[]))

    inserted = await scrape_watchlist_for_user(user_id=1, db=db)

    assert inserted == 0


# ---------------------------------------------------------------------------
# Greenhouse entry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_greenhouse_entry_inserts_jobs():
    profile = _make_profile(watched_companies=[
        {"name": "Acme Corp", "url": "https://boards.greenhouse.io/acme"},
    ])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),
        _jp_insert_exec(42),
        _ujp_insert_exec(True),
    ]

    with patch(
        "app.pipeline.daily_scrape.scrape_greenhouse",
        AsyncMock(return_value=[_make_scraped_job("https://boards.greenhouse.io/acme/jobs/999")]),
    ) as mock_gh:
        inserted = await scrape_watchlist_for_user(user_id=1, db=db)

    mock_gh.assert_called_once_with("https://boards.greenhouse.io/acme", "Acme Corp")
    assert inserted == 1


# ---------------------------------------------------------------------------
# Workday entry — loops over target_titles as search queries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workday_entry_queries_each_target_title():
    profile = _make_profile(
        watched_companies=[{"name": "UOB", "url": "https://uobgroup.wd3.myworkdayjobs.com/UOBExternal"}],
        target_titles=["Engineer", "Analyst"],
    )
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),
        _jp_insert_exec(1), _ujp_insert_exec(True),
        _jp_insert_exec(2), _ujp_insert_exec(True),
    ]

    async def _fake_workday(url, name, query, max_results):
        return [_make_scraped_job(f"https://uobgroup.wd3.myworkdayjobs.com/UOBExternal/job/x_{query}")]

    with patch("app.pipeline.daily_scrape.scrape_workday", side_effect=_fake_workday) as mock_wd:
        inserted = await scrape_watchlist_for_user(user_id=1, db=db)

    assert mock_wd.call_count == 2
    called_queries = {c.kwargs["query"] for c in mock_wd.call_args_list}
    assert called_queries == {"Engineer", "Analyst"}
    assert inserted == 2


@pytest.mark.asyncio
async def test_workday_entry_with_no_target_titles_queries_once_unfiltered():
    profile = _make_profile(
        watched_companies=[{"name": "UOB", "url": "https://uobgroup.wd3.myworkdayjobs.com/UOBExternal"}],
        target_titles=[],
    )
    db = AsyncMock()
    db.execute.side_effect = [_profile_exec(profile)]

    with patch(
        "app.pipeline.daily_scrape.scrape_workday", AsyncMock(return_value=[]),
    ) as mock_wd:
        inserted = await scrape_watchlist_for_user(user_id=1, db=db)

    mock_wd.assert_called_once()
    assert mock_wd.call_args.kwargs["query"] == ""
    assert inserted == 0


# ---------------------------------------------------------------------------
# Unsupported platform — skipped, not an error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unsupported_platform_is_skipped_not_errored():
    profile = _make_profile(watched_companies=[
        {"name": "SomeCo", "url": "https://careers.someco.com/jobs"},
    ])
    db = AsyncMock()
    db.execute.side_effect = [_profile_exec(profile)]

    inserted = await scrape_watchlist_for_user(user_id=1, db=db)

    assert inserted == 0
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# One company's scraper failure doesn't abort the rest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_one_company_failure_does_not_abort_others():
    profile = _make_profile(watched_companies=[
        {"name": "Broken Co", "url": "https://boards.greenhouse.io/broken"},
        {"name": "Acme Corp", "url": "https://boards.greenhouse.io/acme"},
    ])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),
        _jp_insert_exec(42),
        _ujp_insert_exec(True),
    ]

    async def _fake_greenhouse(url, name):
        if name == "Broken Co":
            raise RuntimeError("boom")
        return [_make_scraped_job("https://boards.greenhouse.io/acme/jobs/1")]

    with patch("app.pipeline.daily_scrape.scrape_greenhouse", side_effect=_fake_greenhouse):
        inserted = await scrape_watchlist_for_user(user_id=1, db=db)

    assert inserted == 1
