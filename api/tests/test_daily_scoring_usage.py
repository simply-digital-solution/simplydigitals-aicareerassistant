"""
Unit tests for daily scoring usage (cost guard).
Covers: _get_scorings_today, _increment_scorings_today,
        score_next_batch cap, score_single_job cap, score_jobs_by_ids cap,
        GET /api/v1/scoring/usage endpoint.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(execute_returns: list):
    """Build a mock AsyncSession whose execute() calls return items in order."""
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=execute_returns)
    db.commit = AsyncMock()
    return db


def _row(value):
    """Mock a single-value fetchone result."""
    r = MagicMock()
    r.fetchone.return_value = (value,)
    return r


def _no_row():
    """Mock an empty fetchone (no row)."""
    r = MagicMock()
    r.fetchone.return_value = None
    return r


# ---------------------------------------------------------------------------
# _get_scorings_today
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_scorings_today_returns_count():
    from app.pipeline.llm_scorer import _get_scorings_today
    db = _make_db([_row(23)])
    result = await _get_scorings_today(db, user_id=1)
    assert result == 23


@pytest.mark.asyncio
async def test_get_scorings_today_returns_zero_when_no_row():
    from app.pipeline.llm_scorer import _get_scorings_today
    db = _make_db([_no_row()])
    result = await _get_scorings_today(db, user_id=1)
    assert result == 0


# ---------------------------------------------------------------------------
# _increment_scorings_today
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_increment_scorings_today_upserts():
    from app.pipeline.llm_scorer import _increment_scorings_today
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=MagicMock())
    await _increment_scorings_today(db, user_id=1, count=5)
    assert db.execute.call_count == 1
    sql = str(db.execute.call_args[0][0])
    assert "INSERT INTO daily_scoring_usage" in sql
    assert "ON CONFLICT" in sql
    # Must use qualified table name to avoid AmbiguousColumnError on PostgreSQL
    assert "daily_scoring_usage.jobs_scored" in sql


# ---------------------------------------------------------------------------
# score_next_batch — daily limit enforced
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_next_batch_skips_when_limit_reached():
    """When user has used all 50 scorings today, batch returns False immediately."""
    from app.pipeline.llm_scorer import score_next_batch

    # First execute: job SELECT returns 1 job row (new schema: jp_id, user_id)
    job_row = MagicMock()
    job_row.__getitem__ = lambda self, k: {"user_id": 1, "jp_id": 10, "title": "Dev",
                                            "company": "X", "url": "u", "description": "d",
                                            "inferred_industries": "[]"}[k]
    jobs_result = MagicMock()
    jobs_result.mappings.return_value.all.return_value = [job_row]

    # Second execute: daily_scoring_usage returns 50 (limit hit)
    usage_result = _row(50)

    db = _make_db([jobs_result, usage_result])

    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(scorer_batch_size=20, max_scorings_per_user_per_day=50)
        result = await score_next_batch(db)

    assert result is False


@pytest.mark.asyncio
async def test_score_next_batch_trims_to_remaining_slots():
    """Batch is trimmed to remaining slots when fewer than batch_size remain."""
    from app.pipeline.llm_scorer import score_next_batch

    # Return 5 job rows but user has 48 scorings today (2 remaining)
    job_rows = []
    for i in range(5):
        r = MagicMock()
        r.__getitem__ = lambda self, k, i=i: {
            "user_id": 1, "jp_id": 10 + i, "title": f"Dev{i}",
            "company": "X", "url": "u", "description": "d", "inferred_industries": "[]"
        }[k]
        job_rows.append(r)

    jobs_result = MagicMock()
    jobs_result.mappings.return_value.all.return_value = job_rows
    usage_result = _row(48)  # 2 remaining

    # Use a flexible db mock that returns usage for index 1, generic mock otherwise
    db = AsyncMock(spec=AsyncSession)
    call_count = 0

    async def smart_execute(sql, params=None):
        nonlocal call_count
        result = jobs_result if call_count == 0 else (usage_result if call_count == 1 else MagicMock())
        call_count += 1
        return result

    db.execute = smart_execute
    db.commit = AsyncMock()

    scored_ids = []

    async def fake_run_agent(profile, job_postings, **kwargs):
        scored_ids.extend([j["job_id"] for j in job_postings])
        output = MagicMock()
        output.opportunities = []
        return output, {"model": "test"}

    with (
        patch("app.pipeline.llm_scorer.get_settings") as mock_cfg,
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer._build_feedback_examples", AsyncMock(return_value="")),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_run_agent),
        patch("app.pipeline.llm_scorer._increment_scorings_today", AsyncMock()),
    ):
        mock_cfg.return_value = MagicMock(scorer_batch_size=20, max_scorings_per_user_per_day=50)
        await score_next_batch(db)

    # Only 2 jobs should have been sent to the LLM
    assert len(scored_ids) == 2


# ---------------------------------------------------------------------------
# score_single_job — daily limit enforced
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_single_job_blocked_at_limit():
    """score_single_job returns False immediately when daily limit is reached."""
    from app.pipeline.llm_scorer import score_single_job

    job_row = MagicMock()
    job_row.mappings.return_value.first.return_value = {
        "jp_id": 1, "user_id": 1, "title": "Dev", "company": "X",
        "url": "u", "description": "d", "inferred_industries": "[]"
    }
    app_check = _no_row()   # no advanced application
    usage_result = _row(50)  # limit reached

    db = _make_db([job_row, app_check, usage_result])

    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(max_scorings_per_user_per_day=50)
        result = await score_single_job(db, job_id=1)

    assert result is False


# ---------------------------------------------------------------------------
# score_jobs_by_ids — daily limit enforced
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_jobs_by_ids_blocked_at_limit():
    """score_jobs_by_ids returns all False when daily limit is reached."""
    from app.pipeline.llm_scorer import score_jobs_by_ids

    job_row = MagicMock()
    job_row.__getitem__ = lambda self, k: {
        "jp_id": 1, "user_id": 1, "title": "Dev", "company": "X",
        "url": "u", "description": "d", "inferred_industries": "[]"
    }[k]
    jobs_result = MagicMock()
    jobs_result.mappings.return_value.all.return_value = [job_row]

    adv_result = MagicMock()
    adv_result.fetchall.return_value = []  # no advanced apps

    usage_result = _row(50)  # limit reached

    db = _make_db([jobs_result, adv_result, usage_result])

    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(max_scorings_per_user_per_day=50)
        result = await score_jobs_by_ids(db, job_ids=[1])

    assert result == {1: False}


# ---------------------------------------------------------------------------
# GET /api/v1/scoring/usage endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scoring_usage_endpoint_returns_correct_counts():
    from app.modules.scoring.router import get_scoring_usage

    db = _make_db([_row(12)])
    user = MagicMock()
    user.id = 1

    with patch("app.modules.scoring.router.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(max_scorings_per_user_per_day=50)
        result = await get_scoring_usage(db=db, current_user=user)

    assert result["jobs_scored_today"] == 12
    assert result["daily_limit"] == 50
    assert result["remaining"] == 38


@pytest.mark.asyncio
async def test_scoring_usage_endpoint_remaining_never_negative():
    from app.modules.scoring.router import get_scoring_usage

    db = _make_db([_row(55)])  # over limit somehow
    user = MagicMock()
    user.id = 1

    with patch("app.modules.scoring.router.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(max_scorings_per_user_per_day=50)
        result = await get_scoring_usage(db=db, current_user=user)

    assert result["remaining"] == 0
