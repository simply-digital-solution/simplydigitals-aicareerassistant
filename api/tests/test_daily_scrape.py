"""
Unit tests for api/app/pipeline/daily_scrape.py

All external calls (MCF scraper, DB) are mocked so tests run without a live
database or network connection.

Per-job execute() call sequence (after profile select):
  1. INSERT INTO job_postings ... ON CONFLICT ... RETURNING id → .fetchone() returns (id,)
  2. INSERT INTO user_job_postings ... ON CONFLICT DO NOTHING RETURNING id → .fetchone() returns (id,) or None
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


def _jp_insert_exec(job_id=42):
    """Simulates job_postings INSERT ... RETURNING id."""
    m = MagicMock()
    m.fetchone.return_value = (job_id,)
    return m


def _ujp_insert_exec(inserted=True):
    """Simulates user_job_postings INSERT ON CONFLICT DO NOTHING RETURNING id."""
    m = MagicMock()
    m.fetchone.return_value = (1,) if inserted else None
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
# scrape_for_user — happy path: new job inserted into both tables
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inserts_new_job():
    profile = _make_profile(target_titles=["Data Engineer"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),   # SELECT profile
        _jp_insert_exec(42),      # INSERT job_postings RETURNING id
        _ujp_insert_exec(True),   # INSERT user_job_postings RETURNING id
    ]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture",
               AsyncMock(return_value=[_make_job()])):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 1
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# scrape_for_user — same mcf_uuid, user_job_postings already exists → 0 inserted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_day_duplicate_is_skipped():
    profile = _make_profile(target_titles=["Data Engineer"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),   # SELECT profile
        _jp_insert_exec(42),      # job_postings upsert returns existing id
        _ujp_insert_exec(False),  # user_job_postings already exists → DO NOTHING
    ]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture",
               AsyncMock(return_value=[_make_job(posted_at="2026-06-14T10:00:00Z")])):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 0
    assert db.execute.call_count == 3


# ---------------------------------------------------------------------------
# scrape_for_user — new mcf_uuid → inserted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_different_date_not_duplicate():
    profile = _make_profile(target_titles=["Data Engineer"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),
        _jp_insert_exec(43),
        _ujp_insert_exec(True),
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

    # Filtered before DB insert — only 1 execute call (profile select)
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
        _jp_insert_exec(44),
        _ujp_insert_exec(True),
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
# Helpers for scrape_for_all_users (get_db_context-based)
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager

def _make_get_db_context(user_ids: list[int]):
    """Returns a get_db_context that yields a fresh AsyncMock each call."""
    call_count = 0

    @asynccontextmanager
    async def get_db_context():
        nonlocal call_count
        db = AsyncMock()
        if call_count == 0:
            # First call: return user IDs
            users_exec = MagicMock()
            users_exec.fetchall.return_value = [(uid,) for uid in user_ids]
            db.execute.return_value = users_exec
        call_count += 1
        yield db

    return get_db_context


# ---------------------------------------------------------------------------
# scrape_for_all_users — iterates all user IDs, each gets own session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_for_all_users_calls_each_user():
    get_db_context = _make_get_db_context([1, 2])

    with patch("app.pipeline.daily_scrape.scrape_for_user",
               AsyncMock(return_value=5)) as mock_scrape:
        await scrape_for_all_users(get_db_context)

    assert mock_scrape.call_count == 2


# ---------------------------------------------------------------------------
# scrape_for_all_users — one user fails, others still run (session isolation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_for_all_users_continues_on_error():
    get_db_context = _make_get_db_context([1, 2])
    call_count = 0

    async def _scrape(uid, _db):
        nonlocal call_count
        call_count += 1
        if uid == 1:
            raise RuntimeError("user 1 exploded")
        return 3

    with patch("app.pipeline.daily_scrape.scrape_for_user", _scrape):
        await scrape_for_all_users(get_db_context)

    # user 2 must still run even though user 1 failed
    assert call_count == 2


# ---------------------------------------------------------------------------
# scrape_for_all_users — each user gets an independent DB session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_for_all_users_uses_separate_sessions():
    """Each user's scrape should receive its own db session, not a shared one."""
    sessions_seen: list = []
    get_db_context = _make_get_db_context([1, 2])

    async def _capture_session(uid, db):
        sessions_seen.append(db)
        return 0

    with patch("app.pipeline.daily_scrape.scrape_for_user", _capture_session):
        await scrape_for_all_users(get_db_context)

    assert len(sessions_seen) == 2
    # Each call received a different session object
    assert sessions_seen[0] is not sessions_seen[1]


# ---------------------------------------------------------------------------
# scrape_for_user — INSERT uses boolean false for scored column
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_uses_boolean_false_for_scored():
    """scored column in user_job_postings must be inserted as boolean false."""
    profile = _make_profile(target_titles=["Data Engineer"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),
        _jp_insert_exec(42),
        _ujp_insert_exec(True),
    ]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture",
               AsyncMock(return_value=[_make_job()])):
        await scrape_for_user(user_id=1, db=db)

    # Find the user_job_postings INSERT call (third execute call)
    insert_call = db.execute.call_args_list[2]
    sql = str(insert_call.args[0])
    assert "user_job_postings" in sql
    assert "false" in sql.lower()
