"""
Unit tests for score_single_job() in llm_scorer.py
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
        "id": job_id, "user_id": user_id,
        "title": "Software Engineer", "company": "TechCo",
        "url": "https://example.com/job/1",
        "description": "Build APIs",
        "inferred_industries": '["Technology & Software"]',
    }


def _make_db(job_row=None):
    db = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value.first.return_value = job_row
    feedback_result = MagicMock()
    feedback_result.mappings.return_value.all.return_value = []
    update_result = MagicMock()
    db.execute.side_effect = [select_result, feedback_result, update_result]
    return db


def _make_opportunity(job_id=1, fit_score=0.85):
    opp = MagicMock()
    opp.job_id            = job_id
    opp.fit_score         = fit_score
    opp.reasons           = ["Strong match"]
    opp.risks             = ["One risk"]
    opp.key_keywords      = ["Python"]
    opp.scoring_breakdown = []
    opp.recommendation    = "Apply."
    opp.inferred_industries = ["Technology & Software"]
    return opp


def _make_result(job_id=1, fit_score=0.85):
    result = MagicMock()
    result.opportunities = [_make_opportunity(job_id=job_id, fit_score=fit_score)]
    return result


# ---------------------------------------------------------------------------
# Job not found → returns False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_not_found_returns_false():
    db = _make_db(job_row=None)

    with patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})):
        ok = await score_single_job(db, job_id=999)

    assert ok is False
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path — job scored and written to DB
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
    update_params = db.execute.call_args_list[2].args[1]
    assert update_params["fit_score"] == 0.82
    assert update_params["id"] == 1


# ---------------------------------------------------------------------------
# Agent returns AgentError → returns False, error written
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
    update_params = db.execute.call_args_list[2].args[1]
    assert "parse failed" in update_params["err"]


# ---------------------------------------------------------------------------
# Agent raises exception → returns False, error written
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
    update_params = db.execute.call_args_list[2].args[1]
    assert "RuntimeError" in update_params["err"]


# ---------------------------------------------------------------------------
# Missing job_id in response → returns False, error written
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_job_id_in_response_returns_false():
    db = _make_db(_make_job_row(job_id=1))

    # LLM returns job_id=99 instead of 1
    result = _make_result(job_id=99, fit_score=0.5)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        ok = await score_single_job(db, job_id=1)

    assert ok is False
    update_params = db.execute.call_args_list[2].args[1]
    assert "Missing" in update_params["err"]


# ---------------------------------------------------------------------------
# Single job dict sent to agent (not a batch)
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
