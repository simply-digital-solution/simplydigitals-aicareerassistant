"""
Unit tests for api/app/pipeline/daily_scrape.py

All external calls (MCF scraper, DB) are mocked so tests run without a live
database or network connection.

Per-job execute() call sequence (after profile select):
  1. INSERT INTO job_postings ... ON CONFLICT ... RETURNING id → .fetchone() returns (id,)
  2. INSERT INTO user_job_postings ... ON CONFLICT DO NOTHING RETURNING id → .fetchone() returns (id,) or None
"""
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.pipeline.daily_scrape import (
    scrape_for_all_users,
    scrape_for_user,
    scrape_watchlist_for_user,
)


@pytest.fixture(autouse=True)
def _no_efc_by_default():
    """
    scrape_for_user() also queries eFinancialCareers alongside MCF. Patch it
    to return [] by default so existing MCF-focused tests aren't affected
    and none of them make a real network call; tests that care about eFC
    behavior override this patch explicitly.
    """
    with patch("app.pipeline.daily_scrape.scrape_efinancialcareers", AsyncMock(return_value=[])):
        yield


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
# scrape_for_user — eFinancialCareers results are merged in alongside MCF
# ---------------------------------------------------------------------------

def _make_efc_job(external_id="efinancialcareers:999", url="https://www.efinancialcareers.sg/jobs-x.id999"):
    return {
        "url": url,
        "external_id": external_id,
        "title": "Delivery Manager",
        "company": "Some Bank",
        "location": "Singapore",
        "description": "Lead delivery",
        "inferred_industries": [],
        "posted_at": None,
        "source": "efinancialcareers",
    }


@pytest.mark.asyncio
async def test_efc_jobs_merged_in_alongside_mcf():
    """
    scrape_for_user queries eFinancialCareers once per _EFC_LOCATIONS entry
    — mock a distinct job per call so each produces a real new insert,
    rather than all calls returning the same job (which would legitimately
    dedupe via ON CONFLICT after the first).
    """
    from app.pipeline.daily_scrape import _EFC_LOCATIONS
    num_locations = len(_EFC_LOCATIONS)

    profile = _make_profile(target_titles=["Delivery Manager"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),
        _jp_insert_exec(1), _ujp_insert_exec(True),   # MCF job
    ] + [x for i in range(num_locations) for x in (_jp_insert_exec(100 + i), _ujp_insert_exec(True))]

    mcf_job = _make_job(url="https://www.mycareersfuture.gov.sg/job/abc", mcf_uuid="abc")
    efc_jobs_by_location = [
        _make_efc_job(external_id=f"efinancialcareers:{i}", url=f"https://www.efinancialcareers.sg/jobs-x.id{i}")
        for i in range(num_locations)
    ]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[mcf_job])), \
         patch("app.pipeline.daily_scrape.scrape_efinancialcareers",
               AsyncMock(side_effect=lambda **kwargs: [efc_jobs_by_location.pop(0)])):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 1 + num_locations


@pytest.mark.asyncio
async def test_efc_queried_once_per_configured_location():
    from app.pipeline.daily_scrape import _EFC_LOCATIONS

    profile = _make_profile(target_titles=["Delivery Manager"], target_industries=[])
    db = AsyncMock()
    db.execute.return_value = _profile_exec(profile)

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[])), \
         patch("app.pipeline.daily_scrape.scrape_efinancialcareers",
               AsyncMock(return_value=[])) as mock_efc:
        await scrape_for_user(user_id=1, db=db)

    queried_locations = {c.kwargs["location"] for c in mock_efc.call_args_list}
    assert queried_locations == set(_EFC_LOCATIONS.keys())


# ---------------------------------------------------------------------------
# scrape_for_user — sources parameter restricts which aggregators run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sources_mcf_only_skips_efc_entirely():
    profile = _make_profile(target_titles=["Delivery Manager"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [_profile_exec(profile), _jp_insert_exec(1), _ujp_insert_exec(True)]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[_make_job()])) as mock_mcf, \
         patch("app.pipeline.daily_scrape.scrape_efinancialcareers", AsyncMock(return_value=[])) as mock_efc:
        inserted = await scrape_for_user(user_id=1, db=db, sources={"mycareersfuture"})

    mock_mcf.assert_called_once()
    mock_efc.assert_not_called()
    assert inserted == 1


@pytest.mark.asyncio
async def test_sources_efc_only_skips_mcf_entirely():
    from app.pipeline.daily_scrape import _EFC_LOCATIONS
    num_locations = len(_EFC_LOCATIONS)

    profile = _make_profile(target_titles=["Delivery Manager"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [_profile_exec(profile)] + \
        [x for i in range(num_locations) for x in (_jp_insert_exec(100 + i), _ujp_insert_exec(True))]

    efc_jobs_by_location = [
        _make_efc_job(external_id=f"efinancialcareers:{i}", url=f"https://www.efinancialcareers.sg/jobs-x.id{i}")
        for i in range(num_locations)
    ]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[])) as mock_mcf, \
         patch("app.pipeline.daily_scrape.scrape_efinancialcareers",
               AsyncMock(side_effect=lambda **kwargs: [efc_jobs_by_location.pop(0)])):
        inserted = await scrape_for_user(user_id=1, db=db, sources={"efinancialcareers"})

    mock_mcf.assert_not_called()
    assert inserted == num_locations


@pytest.mark.asyncio
async def test_efc_locations_restricts_to_given_set():
    profile = _make_profile(target_titles=["Delivery Manager"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [_profile_exec(profile), _jp_insert_exec(1), _ujp_insert_exec(True)]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[])), \
         patch("app.pipeline.daily_scrape.scrape_efinancialcareers",
               AsyncMock(return_value=[_make_efc_job()])) as mock_efc:
        inserted = await scrape_for_user(
            user_id=1, db=db, sources={"efinancialcareers"}, efc_locations={"singapore"},
        )

    mock_efc.assert_called_once()
    assert mock_efc.call_args.kwargs["location"] == "singapore"
    assert inserted == 1


@pytest.mark.asyncio
async def test_efc_locations_none_searches_all_configured_same_as_before():
    """Omitting efc_locations must preserve today's behavior exactly — the
    daily scheduler calls scrape_for_user without this argument."""
    from app.pipeline.daily_scrape import _EFC_LOCATIONS
    num_locations = len(_EFC_LOCATIONS)

    profile = _make_profile(target_titles=["Delivery Manager"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [_profile_exec(profile)] + \
        [x for i in range(num_locations) for x in (_jp_insert_exec(100 + i), _ujp_insert_exec(True))]

    efc_jobs_by_location = [
        _make_efc_job(external_id=f"efinancialcareers:{i}", url=f"https://www.efinancialcareers.sg/jobs-x.id{i}")
        for i in range(num_locations)
    ]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[])), \
         patch("app.pipeline.daily_scrape.scrape_efinancialcareers",
               AsyncMock(side_effect=lambda **kwargs: [efc_jobs_by_location.pop(0)])) as mock_efc:
        inserted = await scrape_for_user(user_id=1, db=db, sources={"efinancialcareers"})

    queried_locations = {c.kwargs["location"] for c in mock_efc.call_args_list}
    assert queried_locations == set(_EFC_LOCATIONS.keys())
    assert inserted == num_locations


@pytest.mark.asyncio
async def test_sources_none_runs_both_same_as_before():
    """Omitting sources must preserve today's behavior exactly — the daily
    scheduler calls scrape_for_user without this argument."""
    from app.pipeline.daily_scrape import _EFC_LOCATIONS
    num_locations = len(_EFC_LOCATIONS)

    profile = _make_profile(target_titles=["Delivery Manager"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),
        _jp_insert_exec(1), _ujp_insert_exec(True),
    ] + [x for i in range(num_locations) for x in (_jp_insert_exec(100 + i), _ujp_insert_exec(True))]

    mcf_job = _make_job(url="https://www.mycareersfuture.gov.sg/job/abc", mcf_uuid="abc")
    efc_jobs_by_location = [
        _make_efc_job(external_id=f"efinancialcareers:{i}", url=f"https://www.efinancialcareers.sg/jobs-x.id{i}")
        for i in range(num_locations)
    ]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[mcf_job])) as mock_mcf, \
         patch("app.pipeline.daily_scrape.scrape_efinancialcareers",
               AsyncMock(side_effect=lambda **kwargs: [efc_jobs_by_location.pop(0)])) as mock_efc:
        inserted = await scrape_for_user(user_id=1, db=db)

    mock_mcf.assert_called_once()
    assert mock_efc.call_count == num_locations
    assert inserted == 1 + num_locations


@pytest.mark.asyncio
async def test_efc_failure_does_not_abort_mcf_results():
    profile = _make_profile(target_titles=["Delivery Manager"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),
        _jp_insert_exec(1), _ujp_insert_exec(True),
    ]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", AsyncMock(return_value=[_make_job()])), \
         patch("app.pipeline.daily_scrape.scrape_efinancialcareers",
               AsyncMock(side_effect=RuntimeError("eFC down"))):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 1


@pytest.mark.asyncio
async def test_mcf_failure_does_not_prevent_efc_results():
    """
    Only the first location call returns a job — keeps this test's DB mock
    to a single insert pair, since full multi-location coverage is already
    exercised by test_efc_jobs_merged_in_alongside_mcf.
    """
    from app.pipeline.daily_scrape import _EFC_LOCATIONS
    num_locations = len(_EFC_LOCATIONS)

    profile = _make_profile(target_titles=["Delivery Manager"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),
        _jp_insert_exec(1), _ujp_insert_exec(True),
    ]

    efc_results = [[_make_efc_job()]] + [[]] * (num_locations - 1)

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture",
               AsyncMock(side_effect=RuntimeError("MCF down"))), \
         patch("app.pipeline.daily_scrape.scrape_efinancialcareers",
               AsyncMock(side_effect=lambda **kwargs: efc_results.pop(0))):
        inserted = await scrape_for_user(user_id=1, db=db)

    assert inserted == 1


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
# Dedup key derivation — external_id preferred over URL-derived uuid,
# and truncated to fit job_postings.mcf_uuid's varchar(100) limit.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_external_id_preferred_over_url_derived_uuid():
    from datetime import datetime, timezone

    from app.pipeline.daily_scrape import _insert_jobs_for_user

    db = AsyncMock()
    db.execute.side_effect = [_jp_insert_exec(1), _ujp_insert_exec(True)]

    job = _make_job(url="https://example.com/job/short-slug")
    job["external_id"] = "workday:acme:JR12345"

    await _insert_jobs_for_user(user_id=1, jobs=[job], db=db, now=datetime.now(timezone.utc))

    insert_call = db.execute.call_args_list[0]
    assert insert_call.args[1]["uuid"] == "workday:acme:JR12345"


@pytest.mark.asyncio
async def test_long_url_derived_uuid_is_truncated_to_100_chars():
    from datetime import datetime, timezone

    from app.pipeline.daily_scrape import _insert_jobs_for_user

    db = AsyncMock()
    db.execute.side_effect = [_jp_insert_exec(1), _ujp_insert_exec(True)]

    long_slug = "a" * 150
    job = _make_job(url=f"https://example.com/job/{long_slug}")

    await _insert_jobs_for_user(user_id=1, jobs=[job], db=db, now=datetime.now(timezone.utc))

    insert_call = db.execute.call_args_list[0]
    assert len(insert_call.args[1]["uuid"]) == 100


# ---------------------------------------------------------------------------
# source column — defaults to "mycareersfuture", passes through scraper's
# own value otherwise, and is never overwritten on a conflict-update.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_source_defaults_to_mycareersfuture_when_absent():
    from datetime import datetime, timezone

    from app.pipeline.daily_scrape import _insert_jobs_for_user

    db = AsyncMock()
    db.execute.side_effect = [_jp_insert_exec(1), _ujp_insert_exec(True)]

    job = _make_job()  # no "source" key — mirrors scrape_mycareersfuture()'s dicts

    await _insert_jobs_for_user(user_id=1, jobs=[job], db=db, now=datetime.now(timezone.utc))

    insert_call = db.execute.call_args_list[0]
    assert insert_call.args[1]["source"] == "mycareersfuture"


@pytest.mark.asyncio
async def test_source_passes_through_scraper_value():
    from datetime import datetime, timezone

    from app.pipeline.daily_scrape import _insert_jobs_for_user

    db = AsyncMock()
    db.execute.side_effect = [_jp_insert_exec(1), _ujp_insert_exec(True)]

    job = _make_job()
    job["source"] = "workday"

    await _insert_jobs_for_user(user_id=1, jobs=[job], db=db, now=datetime.now(timezone.utc))

    insert_call = db.execute.call_args_list[0]
    assert insert_call.args[1]["source"] == "workday"


@pytest.mark.asyncio
async def test_source_not_overwritten_in_conflict_update_clause():
    """
    A job's original source shouldn't change on rescrape — verify the SQL's
    ON CONFLICT DO UPDATE clause never assigns source, regardless of the
    value passed as a bind parameter.
    """
    from datetime import datetime, timezone

    from app.pipeline.daily_scrape import _insert_jobs_for_user

    db = AsyncMock()
    db.execute.side_effect = [_jp_insert_exec(1), _ujp_insert_exec(True)]

    job = _make_job()
    job["source"] = "greenhouse"

    await _insert_jobs_for_user(user_id=1, jobs=[job], db=db, now=datetime.now(timezone.utc))

    insert_sql = db.execute.call_args_list[0].args[0].text
    update_clause = insert_sql.split("DO UPDATE SET", 1)[1].split("RETURNING", 1)[0]
    assert "source" not in update_clause


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


@pytest.mark.asyncio
async def test_scrape_for_all_users_also_scrapes_watchlist():
    get_db_context = _make_get_db_context([1, 2])

    with patch("app.pipeline.daily_scrape.scrape_for_user", AsyncMock(return_value=5)), \
         patch("app.pipeline.daily_scrape.scrape_watchlist_for_user",
               AsyncMock(return_value=0)) as mock_watchlist:
        await scrape_for_all_users(get_db_context)

    assert mock_watchlist.call_count == 2


@pytest.mark.asyncio
async def test_watchlist_scrape_failure_does_not_abort_other_users():
    get_db_context = _make_get_db_context([1, 2])

    async def _watchlist_scrape(uid, _db):
        if uid == 1:
            raise RuntimeError("boom")
        return 0

    with patch("app.pipeline.daily_scrape.scrape_for_user", AsyncMock(return_value=0)), \
         patch("app.pipeline.daily_scrape.scrape_watchlist_for_user",
               side_effect=_watchlist_scrape) as mock_watchlist:
        await scrape_for_all_users(get_db_context)

    assert mock_watchlist.call_count == 2


# ---------------------------------------------------------------------------
# scrape_for_all_users — one user fails, others still run (session isolation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scrape_for_all_users_continues_on_error():
    get_db_context = _make_get_db_context([1, 2])
    call_count = 0

    async def _scrape(uid, _db, **kwargs):
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

    async def _capture_session(uid, db, **kwargs):
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
async def test_insert_uses_idle_scoring_status():
    """New rows in user_job_postings must be inserted with scoring_status='idle'."""
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
    assert "scoring_status" in sql
    assert "idle" in sql


@pytest.mark.asyncio
async def test_insert_relies_on_db_default_for_created_at():
    """
    user_job_postings.created_at has a server_default=now() (see migration
    802cae45901c) — the INSERT must not pass an explicit value, so every
    row genuinely reflects the DB's own insert time rather than
    app-server clock drift.
    """
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

    insert_call = db.execute.call_args_list[2]
    sql = str(insert_call.args[0])
    params = insert_call.args[1]
    assert "created_at" not in sql
    assert "created_at" not in params


# ---------------------------------------------------------------------------
# scrape_for_all_users — industry backfill runs after scrape completes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_industry_backfill_called_after_scrape():
    get_db_context = _make_get_db_context([1])

    with (
        patch("app.pipeline.daily_scrape.scrape_for_user", AsyncMock(return_value=3)),
        patch("app.pipeline.industry_backfill.backfill_industries", AsyncMock(return_value=3)) as mock_backfill,
    ):
        await scrape_for_all_users(get_db_context)

    mock_backfill.assert_called_once()


@pytest.mark.asyncio
async def test_industry_backfill_failure_does_not_abort_scrape():
    """A backfill crash must not propagate — scrape result is already committed."""
    get_db_context = _make_get_db_context([1])

    with (
        patch("app.pipeline.daily_scrape.scrape_for_user", AsyncMock(return_value=2)),
        patch("app.pipeline.industry_backfill.backfill_industries", AsyncMock(side_effect=RuntimeError("gemini down"))),
    ):
        # Should not raise
        await scrape_for_all_users(get_db_context)


# ---------------------------------------------------------------------------
# Graceful shutdown — scrape_for_all_users stops between users
# ---------------------------------------------------------------------------

import asyncio as _asyncio


@pytest.mark.asyncio
async def test_scrape_for_all_users_stops_between_users_on_shutdown():
    """
    When shutdown_event is set before the second user's turn,
    scrape_for_user must not be called for that user.
    """
    event = _asyncio.Event()
    get_db_context = _make_get_db_context([1, 2])
    called_user_ids: list[int] = []

    async def _capture(uid, db, shutdown_event=None):
        called_user_ids.append(uid)
        # Signal shutdown after first user — second user must be skipped
        event.set()
        return 1

    with patch("app.pipeline.daily_scrape.scrape_for_user", side_effect=_capture):
        await scrape_for_all_users(get_db_context, shutdown_event=event)

    assert called_user_ids == [1], f"only user 1 should run before shutdown, got {called_user_ids}"


@pytest.mark.asyncio
async def test_scrape_for_user_stops_between_titles_on_shutdown():
    """
    When shutdown_event is set before the second title iteration,
    the MCF scraper must not be called for that title.
    """
    import json as _json
    event = _asyncio.Event()

    profile = _make_profile(target_titles=["Data Engineer", "ML Engineer"], target_industries=[])
    db = AsyncMock()
    db.execute.side_effect = [
        _profile_exec(profile),
        _jp_insert_exec(42),
        _ujp_insert_exec(True),
    ]

    fetch_count = 0

    async def _mock_scrape(query, max_results):
        nonlocal fetch_count
        fetch_count += 1
        # Signal shutdown after first title fetch — second title must be skipped
        event.set()
        return [_make_job()]

    with patch("app.pipeline.daily_scrape.scrape_mycareersfuture", side_effect=_mock_scrape):
        from app.pipeline.daily_scrape import scrape_for_user
        await scrape_for_user(user_id=1, db=db, shutdown_event=event)

    assert fetch_count == 1, f"only first title should be fetched before shutdown, got {fetch_count}"
