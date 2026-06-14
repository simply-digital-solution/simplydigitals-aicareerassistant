"""
Unit tests for api/app/pipeline/llm_scorer.py

All DB and agent calls are mocked — no live database or LLM needed.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.pipeline.llm_scorer import score_next_job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_with_job(job_row=None):
    """
    Return a mock AsyncSession whose first execute() simulates a job SELECT.
    Subsequent execute() calls simulate UPDATE commits.
    """
    db = AsyncMock()

    select_result = MagicMock()
    if job_row is None:
        select_result.mappings.return_value.first.return_value = None
    else:
        select_result.mappings.return_value.first.return_value = job_row

    update_result = MagicMock()
    db.execute.side_effect = [select_result, update_result]
    return db


def _make_job_row(job_id=1, user_id=42,
                  title="ML Engineer", company="DeepCo",
                  url="https://www.mycareersfuture.gov.sg/job/xyz",
                  description="Build ML models",
                  inferred_industries='["Technology & Software"]'):
    return {
        "id":                  job_id,
        "user_id":             user_id,
        "title":               title,
        "company":             company,
        "url":                 url,
        "description":         description,
        "inferred_industries": inferred_industries,
    }


def _make_opportunity(fit_score=0.85, reasons=None, risks=None, keywords=None):
    opp = MagicMock()
    opp.fit_score    = fit_score
    opp.reasons      = reasons   or ["Strong ML skills match"]
    opp.risks        = risks     or ["No Python 3.11 mentioned"]
    opp.key_keywords = keywords  or ["PyTorch", "SQL"]
    return opp


def _make_research_result(opp=None):
    result = MagicMock()
    result.opportunities = [opp or _make_opportunity()]
    return result


# ---------------------------------------------------------------------------
# Empty queue → returns False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_queue_returns_false():
    db = _db_with_job(job_row=None)

    had_work = await score_next_job(db)

    assert had_work is False
    # No UPDATE should have been issued
    db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Happy path: job scored successfully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_score_writes_result():
    job_row = _make_job_row()
    db      = _db_with_job(job_row)

    opp    = _make_opportunity(fit_score=0.78)
    result = _make_research_result(opp)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        had_work = await score_next_job(db)

    assert had_work is True
    db.commit.assert_called()

    # Verify the UPDATE was executed with fit_score
    update_call = db.execute.call_args_list[1]
    params = update_call.args[1]   # second positional arg to execute()
    assert params["fit_score"] == 0.78
    assert params["id"] == 1


# ---------------------------------------------------------------------------
# Agent raises exception → job marked scored=1, returns True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_exception_marks_job_scored():
    job_row = _make_job_row()
    db      = _db_with_job(job_row)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(side_effect=RuntimeError("LLM timed out"))),
    ):
        had_work = await score_next_job(db)

    assert had_work is True
    db.commit.assert_called()

    # Verify UPDATE was still issued (to avoid infinite retry)
    assert db.execute.call_count == 2


# ---------------------------------------------------------------------------
# Agent returns AgentError → job marked scored=1, returns True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_error_result_marks_job_scored():
    from app.shared.schemas import AgentError

    job_row = _make_job_row()
    db      = _db_with_job(job_row)

    agent_err = AgentError(error="parse failed")

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(agent_err, {}))),
    ):
        had_work = await score_next_job(db)

    assert had_work is True
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# Agent returns result with empty opportunities → job marked scored=1
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_opportunities_marks_job_scored():
    job_row = _make_job_row()
    db      = _db_with_job(job_row)

    empty_result = MagicMock()
    empty_result.opportunities = []

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(return_value=(empty_result, {}))),
    ):
        had_work = await score_next_job(db)

    assert had_work is True
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# inferred_industries is properly deserialized from JSON string
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inferred_industries_deserialized():
    job_row = _make_job_row(inferred_industries='["Banking & Financial Services", "FinTech"]')
    db      = _db_with_job(job_row)

    opp    = _make_opportunity()
    result = _make_research_result(opp)

    captured_job = {}

    async def fake_agent(profile, job_postings, search_filters, db, user_id):
        captured_job.update(job_postings[0])
        return result, {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_next_job(db)

    assert captured_job["inferred_industries"] == ["Banking & Financial Services", "FinTech"]


# ---------------------------------------------------------------------------
# reasons / risks / key_keywords are JSON-encoded in the UPDATE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_fields_json_encoded_in_update():
    job_row = _make_job_row()
    db      = _db_with_job(job_row)

    opp = _make_opportunity(reasons=["r1"], risks=["risk1"], keywords=["k1", "k2"])
    result = _make_research_result(opp)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_job(db)

    params = db.execute.call_args_list[1].args[1]
    assert json.loads(params["reasons"])  == ["r1"]
    assert json.loads(params["risks"])    == ["risk1"]
    assert json.loads(params["keywords"]) == ["k1", "k2"]
