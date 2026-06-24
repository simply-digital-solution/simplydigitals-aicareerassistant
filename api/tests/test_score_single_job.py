"""
Unit tests for score_single_job() in llm_scorer.py

Execute call sequence (success path, user_id provided):
  [0] job SELECT (returns jp_id, user_id, ...)
  [1] application status check SELECT
  [2] lifetime SUM (_get_daily_limit)
  [3] daily scoring usage today (_get_scorings_today)
  [4] rescoring=true UPDATE
  [5] feedback SELECT (_build_feedback_examples)
  [6] _write_score → UPDATE user_job_postings (params: jid, uid, fit_score, ...)
  [7] UPDATE job_postings inferred_industries (params: ind, id)
  [8] _increment_scorings_today INSERT
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.pipeline.llm_scorer import score_single_job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job_row(job_id=1, user_id=42):
    return {
        "jp_id": job_id, "user_id": user_id,
        "title": "Software Engineer", "company": "TechCo",
        "url": "https://example.com/job/1",
        "description": "Build APIs",
        "inferred_industries": '["Technology & Software"]',
    }


def _make_db(job_row=None, advanced_status=False):
    db = AsyncMock()
    # [0] job SELECT
    select_result = MagicMock()
    select_result.mappings.return_value.first.return_value = job_row
    # [1] application status check SELECT
    app_check = MagicMock()
    app_check.fetchone.return_value = (1,) if advanced_status else None
    # [2] lifetime SUM (_get_daily_limit) — existing user → 50 limit
    lifetime_result = MagicMock()
    lifetime_result.fetchone.return_value = (100,)
    # [3] daily scoring usage SELECT today (_get_scorings_today, 0 = under limit)
    usage_result = MagicMock()
    usage_result.fetchone.return_value = (0,)
    # [4] rescoring=true UPDATE
    rescoring_update = MagicMock()
    # [5] feedback SELECT
    feedback_result = MagicMock()
    feedback_result.mappings.return_value.all.return_value = []
    # [6] _write_score UPDATE user_job_postings
    update_result = MagicMock()
    # [7] UPDATE job_postings inferred_industries
    ind_update = MagicMock()
    # [8] _increment_scorings_today INSERT
    increment_result = MagicMock()
    db.execute.side_effect = [
        select_result, app_check, lifetime_result, usage_result, rescoring_update,
        feedback_result, update_result, ind_update, increment_result,
    ]
    return db


def _make_opportunity(job_id=1, fit_score=0.85):
    opp = MagicMock()
    opp.job_id              = job_id
    opp.fit_score           = fit_score
    opp.reasons             = ["Strong match"]
    opp.risks               = ["One risk"]
    opp.key_keywords        = ["Python"]
    opp.scoring_breakdown   = []
    opp.recommendation      = "Apply."
    opp.inferred_industries = ["Technology & Software"]
    return opp


def _make_result(job_id=1, fit_score=0.85):
    result = MagicMock()
    result.opportunities = [_make_opportunity(job_id=job_id, fit_score=fit_score)]
    return result


# ---------------------------------------------------------------------------
# Job not found → returns False, no rescoring flag set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_not_found_returns_false():
    db = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value.first.return_value = None
    db.execute.side_effect = [select_result]

    with patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})):
        ok = await score_single_job(db, job_id=999)

    assert ok is False
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path — rescoring=true set before call, score written on success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_single_score():
    db = _make_db(_make_job_row(job_id=1))
    result = _make_result(job_id=1, fit_score=0.82)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        ok = await score_single_job(db, job_id=1)

    assert ok is True
    db.commit.assert_called()
    # [4] is the rescoring=true UPDATE
    rescoring_sql = db.execute.call_args_list[4].args[0].text
    assert "rescoring=true" in rescoring_sql
    # [6] is the _write_score UPDATE user_job_postings
    update_params = db.execute.call_args_list[6].args[1]
    assert update_params["fit_score"] == 0.82
    assert update_params["jid"] == 1


# ---------------------------------------------------------------------------
# Agent returns AgentError → rescoring=false, error written, old score preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_error_returns_false():
    from app.shared.schemas import AgentError
    db = _make_db(_make_job_row(job_id=1))

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(return_value=(AgentError(error="parse failed"), {}))),
    ):
        ok = await score_single_job(db, job_id=1)

    assert ok is False
    # Error UPDATE is the 7th execute call ([6])
    update_params = db.execute.call_args_list[6].args[1]
    assert "parse failed" in update_params["err"]
    # Must NOT reset scored/fit_score — only rescoring=false and score_error
    update_sql = db.execute.call_args_list[6].args[0].text
    assert "rescoring=false" in update_sql
    assert "scored=false" not in update_sql
    assert "fit_score = NULL" not in update_sql


# ---------------------------------------------------------------------------
# Agent raises exception → rescoring=false, error written, old score preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_exception_returns_false():
    db = _make_db(_make_job_row(job_id=1))

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(side_effect=RuntimeError("timeout"))),
    ):
        ok = await score_single_job(db, job_id=1)

    assert ok is False
    update_params = db.execute.call_args_list[6].args[1]
    assert "RuntimeError" in update_params["err"]
    update_sql = db.execute.call_args_list[6].args[0].text
    assert "rescoring=false" in update_sql
    assert "scored=false" not in update_sql


# ---------------------------------------------------------------------------
# Missing job_id in response → rescoring=false, error written
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_job_id_in_response_returns_false():
    db = _make_db(_make_job_row(job_id=1))
    result = _make_result(job_id=99, fit_score=0.5)  # wrong job_id

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        ok = await score_single_job(db, job_id=1)

    assert ok is False
    update_params = db.execute.call_args_list[6].args[1]
    assert "Missing" in update_params["err"]


# ---------------------------------------------------------------------------
# Single job dict sent to agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_one_job_sent_to_agent():
    db = _make_db(_make_job_row(job_id=5))
    captured = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured["job_postings"] = job_postings
        return _make_result(job_id=5), {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_single_job(db, job_id=5)

    assert len(captured["job_postings"]) == 1
    assert captured["job_postings"][0]["job_id"] == 5


# ---------------------------------------------------------------------------
# max_self_corrections=0 passed (no reflexion retries on single rescore)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_score_passes_max_self_corrections_zero():
    db = _make_db(_make_job_row(job_id=1))
    captured = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured["max_self_corrections"] = kwargs.get("max_self_corrections")
        return _make_result(job_id=1), {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_single_job(db, job_id=1)

    assert captured["max_self_corrections"] == 0


# ---------------------------------------------------------------------------
# Advanced status guard — skip rescoring if application is applied or beyond
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skips_scoring_when_application_in_advanced_status():
    db = _make_db(_make_job_row(job_id=1), advanced_status=True)

    with patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})):
        ok = await score_single_job(db, job_id=1)

    assert ok is False
    db.commit.assert_not_called()
    # Only 2 execute calls: job SELECT + app check (return early)
    assert db.execute.call_count == 2


@pytest.mark.asyncio
async def test_scores_normally_when_application_is_selected():
    db = _make_db(_make_job_row(job_id=1), advanced_status=False)
    result = _make_result(job_id=1, fit_score=0.75)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        ok = await score_single_job(db, job_id=1)

    assert ok is True
