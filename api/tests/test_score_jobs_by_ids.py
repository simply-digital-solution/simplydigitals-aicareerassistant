"""
Unit tests for score_jobs_by_ids() in llm_scorer.py
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.pipeline.llm_scorer import score_jobs_by_ids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job_row(job_id=1, user_id=42):
    return {
        "jp_id": job_id, "user_id": user_id,
        "title": "Engineer", "company": "Co",
        "url": "https://example.com", "description": "Build stuff",
        "inferred_industries": "[]",
    }


def _make_db(job_rows=None, advanced_ids=None):
    db = AsyncMock()
    # [0] job SELECT
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = job_rows or []
    # [1] advanced-status check SELECT
    adv_check = MagicMock()
    adv_check.fetchall.return_value = [(jid,) for jid in (advanced_ids or [])]
    # [2] lifetime SUM (_get_daily_limit) — existing user → 50 limit
    lifetime_result = MagicMock()
    lifetime_result.fetchone.return_value = (100,)
    # [3] daily scoring usage SELECT today (_get_scorings_today, 0 = under limit)
    usage_result = MagicMock()
    usage_result.fetchone.return_value = (0,)
    # [4..N+3] rescoring=1 UPDATEs (one per scoreable job)
    rescoring_update = MagicMock()
    # [N+4] feedback SELECT
    feedback_result = MagicMock()
    feedback_result.mappings.return_value.all.return_value = []
    # remaining: score writes, error updates, increment INSERT
    update_result = MagicMock()
    n_jobs = len(job_rows or [])
    db.execute.side_effect = (
        [select_result, adv_check, lifetime_result, usage_result]
        + [rescoring_update] * max(n_jobs, 1)
        + [feedback_result]
        + [update_result] * 20
    )
    return db


def _make_opp(job_id=1, fit_score=0.8):
    opp = MagicMock()
    opp.job_id = job_id
    opp.fit_score = fit_score
    opp.reasons = ["good"]
    opp.risks = ["risk"]
    opp.key_keywords = ["kw"]
    opp.scoring_breakdown = []
    opp.recommendation = "Apply."
    opp.inferred_industries = ["Technology & Software"]
    return opp


def _make_result(job_ids):
    result = MagicMock()
    result.opportunities = [_make_opp(job_id=jid) for jid in job_ids]
    return result


# ---------------------------------------------------------------------------
# Empty input → empty dict, no DB calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_ids_returns_empty():
    db = AsyncMock()
    result = await score_jobs_by_ids(db, [])
    assert result == {}
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# No jobs found in DB → all False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_jobs_found_returns_all_false():
    db = _make_db(job_rows=[])
    result = await score_jobs_by_ids(db, [1, 2, 3])
    assert result == {1: False, 2: False, 3: False}
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path — all jobs scored, all True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_jobs_scored_returns_true():
    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    db = _make_db(job_rows=rows)
    llm_result = _make_result([1, 2])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer._increment_scorings_today", AsyncMock()),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(return_value=(llm_result, {"model": "gemini-flash-latest"}))),
    ):
        result = await score_jobs_by_ids(db, [1, 2])

    assert result == {1: True, 2: True}
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# Agent returns AgentError → all False, errors written
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_error_marks_all_false():
    from app.shared.schemas import AgentError
    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    db = _make_db(job_rows=rows)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer._increment_scorings_today", AsyncMock()),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(return_value=(AgentError(error="parse failed"), {}))),
    ):
        result = await score_jobs_by_ids(db, [1, 2])

    assert result == {1: False, 2: False}
    db.commit.assert_called()
    # Both jobs should have score_error written — find calls with an "err" param
    update_calls = [c for c in db.execute.call_args_list if c.args[1].get("err")]
    assert len(update_calls) == 2


# ---------------------------------------------------------------------------
# Agent exception → all False, errors written
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_exception_marks_all_false():
    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    db = _make_db(job_rows=rows)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer._increment_scorings_today", AsyncMock()),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(side_effect=RuntimeError("timeout"))),
    ):
        result = await score_jobs_by_ids(db, [1, 2])

    assert result == {1: False, 2: False}


# ---------------------------------------------------------------------------
# LLM returns only one of two jobs → partial results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partial_response_marks_missing_as_false():
    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    db = _make_db(job_rows=rows)
    llm_result = _make_result([1])  # only job 1 returned

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer._increment_scorings_today", AsyncMock()),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(return_value=(llm_result, {}))),
    ):
        result = await score_jobs_by_ids(db, [1, 2])

    assert result[1] is True
    assert result[2] is False


# ---------------------------------------------------------------------------
# scored_by_model written from meta
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scored_by_model_written():
    rows = [_make_job_row(job_id=1)]
    db = _make_db(job_rows=rows)
    llm_result = _make_result([1])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer._increment_scorings_today", AsyncMock()),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(return_value=(llm_result, {"model": "gemini-flash-latest"}))),
    ):
        await score_jobs_by_ids(db, [1])

    # Find the _write_score UPDATE call — it has a "model" param
    write_calls = [c for c in db.execute.call_args_list if c.args[1].get("model") is not None or "model" in c.args[1]]
    assert any(c.args[1].get("model") == "gemini-flash-latest" for c in write_calls)


# ---------------------------------------------------------------------------
# Advanced status guard — jobs in applied/interviewing/etc. are skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_advanced_status_jobs_excluded_from_scoring():
    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    # job 1 is in applied status — should be skipped
    db = _make_db(job_rows=rows, advanced_ids=[1])

    captured = {}
    async def fake_scorer(profile, job_postings, **kwargs):
        captured["job_postings"] = job_postings
        return MagicMock(opportunities=[_make_opp(job_id=2)]), {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer._increment_scorings_today", AsyncMock()),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_scorer),
    ):
        result = await score_jobs_by_ids(db, [1, 2])

    # job 1 skipped (False), job 2 scored (True)
    assert result[1] is False
    assert result[2] is True
    # Only job 2 was sent to the agent
    assert all(j["job_id"] != 1 for j in captured["job_postings"])


@pytest.mark.asyncio
async def test_all_advanced_status_returns_all_false():
    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    db = _make_db(job_rows=rows, advanced_ids=[1, 2])

    with patch("app.pipeline.llm_scorer.run_research_agent") as mock_agent:
        result = await score_jobs_by_ids(db, [1, 2])

    assert result == {1: False, 2: False}
    mock_agent.assert_not_called()
