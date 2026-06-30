"""
Unit tests for daily scoring usage (cost guard).
Covers: _get_scorings_today, _increment_scorings_today, _get_daily_limit,
        score_next_batch cap, score_single_job cap, score_jobs_by_ids cap,
        GET /api/v1/scoring/usage endpoint.

_get_daily_limit adds one DB call (lifetime SUM) before _get_scorings_today.
Call order for limit checks:
  [N]   SELECT SUM(jobs_scored) ... — lifetime total  → _get_daily_limit
  [N+1] SELECT jobs_scored ... WHERE date=today       → _get_scorings_today
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(execute_returns: list):
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=execute_returns)
    db.commit = AsyncMock()
    return db


def _row(value):
    r = MagicMock()
    r.fetchone.return_value = (value,)
    return r


def _no_row():
    r = MagicMock()
    r.fetchone.return_value = None
    return r


def _lifetime(total: int):
    """Mock for _get_daily_limit's SUM(jobs_scored) query."""
    return _row(total)


# ---------------------------------------------------------------------------
# _get_scorings_today
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_scorings_today_returns_count():
    from app.pipeline.llm_scorer import _get_scorings_today
    db = _make_db([_row(23)])
    assert await _get_scorings_today(db, user_id=1) == 23


@pytest.mark.asyncio
async def test_get_scorings_today_returns_zero_when_no_row():
    from app.pipeline.llm_scorer import _get_scorings_today
    db = _make_db([_no_row()])
    assert await _get_scorings_today(db, user_id=1) == 0


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
    assert "daily_scoring_usage.jobs_scored" in sql


# ---------------------------------------------------------------------------
# _get_daily_limit — two-tier logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_new_user_gets_high_limit():
    from app.pipeline.llm_scorer import _get_daily_limit
    db = _make_db([_lifetime(0)])  # never scored anything
    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(new_user_scoring_limit=250, max_scorings_per_user_per_day=50)
        limit = await _get_daily_limit(db, user_id=1)
    assert limit == 250


@pytest.mark.asyncio
async def test_existing_user_gets_standard_limit():
    from app.pipeline.llm_scorer import _get_daily_limit
    db = _make_db([_lifetime(10)])  # has scored before
    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(new_user_scoring_limit=250, max_scorings_per_user_per_day=50)
        limit = await _get_daily_limit(db, user_id=1)
    assert limit == 50


@pytest.mark.asyncio
async def test_user_becomes_existing_after_first_scoring():
    """Once lifetime total > 0, the 50/day limit applies."""
    from app.pipeline.llm_scorer import _get_daily_limit
    db = _make_db([_lifetime(1)])
    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(new_user_scoring_limit=250, max_scorings_per_user_per_day=50)
        limit = await _get_daily_limit(db, user_id=1)
    assert limit == 50


# ---------------------------------------------------------------------------
# score_next_batch — daily limit enforced
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_next_batch_skips_when_limit_reached():
    """Existing user at 50/50 → CTE excludes them, batch SELECT returns empty, returns False."""
    from app.pipeline.llm_scorer import score_next_batch

    # CTE filters out capped users at the SELECT level — _pick_next_job returns no row
    empty_result = MagicMock()
    empty_result.mappings.return_value.all.return_value = []

    db = _make_db([empty_result])

    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(scorer_batch_size=10, new_user_scoring_limit=250, max_scorings_per_user_per_day=50, enable_llm_traffic_controller=False)
        result = await score_next_batch(db)

    assert result is False


@pytest.mark.asyncio
async def test_score_next_batch_new_user_higher_limit():
    """New user with 0 lifetime scored gets 250 limit — not blocked at 50."""
    from app.pipeline.llm_scorer import score_next_batch

    job_row = MagicMock()
    job_row.__getitem__ = lambda self, k: {
        "user_id": 1, "jp_id": 10, "title": "Dev",
        "company": "X", "url": "u", "description": "d", "inferred_industries": "[]"
    }[k]
    jobs_result = MagicMock()
    jobs_result.mappings.return_value.all.return_value = [job_row]

    scored_ids = []

    async def fake_agent(profile, job_postings, **kwargs):
        scored_ids.extend([j["job_id"] for j in job_postings])
        return MagicMock(opportunities=[]), {"model": "test"}

    # CTE handles the limit check — just return the job row and feedback result
    feedback_result = MagicMock()
    feedback_result.mappings.return_value.all.return_value = []

    db = _make_db([jobs_result, feedback_result] + [MagicMock()] * 10)
    db.commit = AsyncMock()

    with (
        patch("app.pipeline.llm_scorer.get_settings") as mock_cfg,
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer._build_feedback_examples", AsyncMock(return_value="")),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
        patch("app.pipeline.llm_scorer._increment_scorings_today", AsyncMock()),
    ):
        mock_cfg.return_value = MagicMock(scorer_batch_size=10, new_user_scoring_limit=250, max_scorings_per_user_per_day=50, enable_llm_traffic_controller=False)
        result = await score_next_batch(db)

    # New user has 250 limit so 50 scored today is fine — should proceed
    assert result is True
    assert len(scored_ids) == 1


@pytest.mark.asyncio
async def test_score_next_batch_scores_one_job_when_slots_remain():
    """score_next_batch scores exactly 1 job when daily slots remain."""
    from app.pipeline.llm_scorer import score_next_batch

    job_row = MagicMock()
    job_row.__getitem__ = lambda self, k: {
        "user_id": 1, "jp_id": 10, "title": "Dev",
        "company": "X", "url": "u", "description": "d", "inferred_industries": "[]"
    }[k]

    jobs_result = MagicMock()
    jobs_result.mappings.return_value.all.return_value = [job_row]

    scored_ids = []

    async def fake_run_agent(profile, job_postings, **kwargs):
        scored_ids.extend([j["job_id"] for j in job_postings])
        opp = MagicMock()
        opp.job_id = job_postings[0]["job_id"]
        opp.fit_score = 0.8
        opp.reasons = []
        opp.risks = []
        opp.key_keywords = []
        opp.scoring_breakdown = []
        opp.recommendation = ""
        opp.inferred_industries = []
        result = MagicMock()
        result.opportunities = [opp]
        return result, {"model": "test"}

    feedback_result = MagicMock()
    feedback_result.mappings.return_value.all.return_value = []

    db = _make_db([jobs_result, feedback_result] + [MagicMock()] * 10)
    db.commit = AsyncMock()

    with (
        patch("app.pipeline.llm_scorer.get_settings") as mock_cfg,
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer._build_feedback_examples", AsyncMock(return_value="")),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_run_agent),
        patch("app.pipeline.llm_scorer._increment_scorings_today", AsyncMock()),
    ):
        mock_cfg.return_value = MagicMock(scorer_batch_size=1, new_user_scoring_limit=250, max_scorings_per_user_per_day=50, enable_llm_traffic_controller=False)
        await score_next_batch(db)

    assert len(scored_ids) == 1
    assert scored_ids[0] == 10


# ---------------------------------------------------------------------------
# score_single_job — daily limit enforced
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_single_job_blocked_at_limit():
    """Existing user at limit → score_single_job returns False."""
    from app.pipeline.llm_scorer import score_single_job

    job_row = MagicMock()
    job_row.mappings.return_value.first.return_value = {
        "jp_id": 1, "user_id": 1, "title": "Dev", "company": "X",
        "url": "u", "description": "d", "inferred_industries": "[]"
    }
    rescoring_not_in_progress = MagicMock()
    rescoring_not_in_progress.scalar.return_value = False
    db = _make_db([
        job_row,                    # job SELECT
        _no_row(),                  # app_check: no advanced application
        rescoring_not_in_progress,  # rescoring_check: not already in progress
        _lifetime(100),             # _get_daily_limit: existing user → 50
        _row(50),                   # _get_scorings_today: at limit
    ])

    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(new_user_scoring_limit=250, max_scorings_per_user_per_day=50)
        result = await score_single_job(db, job_id=1)

    assert result is False


@pytest.mark.asyncio
async def test_score_single_job_skips_if_already_rescoring():
    """score_single_job returns False immediately if rescoring=true — prevents duplicate LLM calls."""
    from app.pipeline.llm_scorer import score_single_job

    job_row = MagicMock()
    job_row.mappings.return_value.first.return_value = {
        "jp_id": 1, "user_id": 1, "title": "Dev", "company": "X",
        "url": "u", "description": "d", "inferred_industries": "[]"
    }
    rescoring_in_progress = MagicMock()
    rescoring_in_progress.scalar.return_value = True
    db = _make_db([
        job_row,               # job SELECT
        _no_row(),             # app_check: no advanced application
        rescoring_in_progress, # rescoring_check: already in progress
    ])

    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(new_user_scoring_limit=250, max_scorings_per_user_per_day=50)
        result = await score_single_job(db, job_id=1)

    assert result is False
    # Daily limit check must NOT have been called (only 3 execute calls, not 5)
    assert db.execute.call_count == 3


@pytest.mark.asyncio
async def test_score_single_job_proceeds_if_not_rescoring():
    """score_single_job proceeds normally when rescoring=false."""
    from app.pipeline.llm_scorer import score_single_job

    job_row = MagicMock()
    job_row.mappings.return_value.first.return_value = {
        "jp_id": 1, "user_id": 1, "title": "Dev", "company": "X",
        "url": "u", "description": "d", "inferred_industries": "[]"
    }
    rescoring_not_in_progress = MagicMock()
    rescoring_not_in_progress.scalar.return_value = False
    db = _make_db([
        job_row,                    # job SELECT
        _no_row(),                  # app_check: no advanced application
        rescoring_not_in_progress,  # rescoring_check: not in progress
        _lifetime(0),               # _get_daily_limit: new user → 250
        _row(0),                    # _get_scorings_today: 0 used
    ] + [MagicMock()] * 10)
    db.commit = AsyncMock()

    async def fake_agent(profile, job_postings, **kwargs):
        return MagicMock(opportunities=[]), {"model": "test"}

    with (
        patch("app.pipeline.llm_scorer.get_settings") as mock_cfg,
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer._build_feedback_examples", AsyncMock(return_value="")),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
        patch("app.pipeline.llm_scorer._increment_scorings_today", AsyncMock()),
    ):
        mock_cfg.return_value = MagicMock(new_user_scoring_limit=250, max_scorings_per_user_per_day=50)
        result = await score_single_job(db, job_id=1)

    # Proceeds past the rescoring check — returns False only because agent returned no opportunities
    assert result is False
    assert db.execute.call_count >= 3  # got past all guards


# ---------------------------------------------------------------------------
# score_jobs_by_ids — daily limit enforced
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_jobs_by_ids_blocked_at_limit():
    """Existing user at limit → score_jobs_by_ids returns all False."""
    from app.pipeline.llm_scorer import score_jobs_by_ids

    job_row = MagicMock()
    job_row.__getitem__ = lambda self, k: {
        "jp_id": 1, "user_id": 1, "title": "Dev", "company": "X",
        "url": "u", "description": "d", "inferred_industries": "[]"
    }[k]
    jobs_result = MagicMock()
    jobs_result.mappings.return_value.all.return_value = [job_row]

    adv_result = MagicMock()
    adv_result.fetchall.return_value = []

    db = _make_db([
        jobs_result,    # job SELECT
        adv_result,     # advanced status check
        _lifetime(100), # _get_daily_limit: existing user → 50
        _row(50),       # _get_scorings_today: at limit
    ])

    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(new_user_scoring_limit=250, max_scorings_per_user_per_day=50)
        result = await score_jobs_by_ids(db, job_ids=[1])

    assert result == {1: False}


# ---------------------------------------------------------------------------
# GET /api/v1/scoring/usage endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scoring_usage_endpoint_new_user():
    """New user sees 250 limit."""
    from app.modules.scoring.router import get_scoring_usage

    db = _make_db([_lifetime(0), _row(5)])  # new user, 5 scored today
    user = MagicMock()
    user.id = 1

    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(new_user_scoring_limit=250, max_scorings_per_user_per_day=50)
        result = await get_scoring_usage(db=db, current_user=user)

    assert result["daily_limit"] == 250
    assert result["jobs_scored_today"] == 5
    assert result["remaining"] == 245


@pytest.mark.asyncio
async def test_scoring_usage_endpoint_existing_user():
    """Existing user sees 50 limit."""
    from app.modules.scoring.router import get_scoring_usage

    db = _make_db([_lifetime(80), _row(12)])  # existing user, 12 scored today
    user = MagicMock()
    user.id = 1

    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(new_user_scoring_limit=250, max_scorings_per_user_per_day=50)
        result = await get_scoring_usage(db=db, current_user=user)

    assert result["daily_limit"] == 50
    assert result["jobs_scored_today"] == 12
    assert result["remaining"] == 38


@pytest.mark.asyncio
async def test_scoring_usage_endpoint_remaining_never_negative():
    from app.modules.scoring.router import get_scoring_usage

    db = _make_db([_lifetime(80), _row(55)])  # over limit
    user = MagicMock()
    user.id = 1

    with patch("app.pipeline.llm_scorer.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(new_user_scoring_limit=250, max_scorings_per_user_per_day=50)
        result = await get_scoring_usage(db=db, current_user=user)

    assert result["remaining"] == 0
