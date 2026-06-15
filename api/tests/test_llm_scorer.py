"""
Unit tests for api/app/pipeline/llm_scorer.py

All DB and agent calls are mocked — no live database or LLM needed.

DB execute() call sequence inside score_next_job:
  1. SELECT job_postings (job SELECT)
  2. SELECT job_feedback (feedback examples)
  3. UPDATE job_postings  (write score back)
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.pipeline.llm_scorer import score_next_job, _build_feedback_examples


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feedback_exec(rows=None):
    """Simulates the job_feedback SELECT."""
    m = MagicMock()
    m.mappings.return_value.all.return_value = rows or []
    return m


def _db_with_job(job_row=None, feedback_rows=None):
    """
    Return a mock AsyncSession.
    execute() side_effect sequence:
      [0] job SELECT
      [1] feedback SELECT
      [2] UPDATE (only reached when a job was found)
    """
    db = AsyncMock()

    select_result = MagicMock()
    if job_row is None:
        select_result.mappings.return_value.first.return_value = None
    else:
        select_result.mappings.return_value.first.return_value = job_row

    feedback_result = _feedback_exec(feedback_rows)
    update_result   = MagicMock()

    db.execute.side_effect = [select_result, feedback_result, update_result]
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


def _make_score_category(category="Technical Skills", jd_experience="Python, SQL",
                          your_profile="Python, PostgreSQL", score=8):
    from app.shared.schemas import ScoreCategory
    return ScoreCategory(category=category, jd_experience=jd_experience,
                         your_profile=your_profile, score=score)


def _make_opportunity(fit_score=0.85, reasons=None, risks=None, keywords=None, breakdown=None):
    opp = MagicMock()
    opp.fit_score       = fit_score
    opp.reasons         = reasons   or ["Strong ML skills match"]
    opp.risks           = risks     or ["No Python 3.11 mentioned"]
    opp.key_keywords    = keywords  or ["PyTorch", "SQL"]
    opp.scoring_breakdown = breakdown if breakdown is not None else []
    return opp


def _make_research_result(opp=None):
    result = MagicMock()
    result.opportunities = [opp or _make_opportunity()]
    return result


def _make_feedback_row(job_title="Data Engineer", company="ACME", relevance="relevant", reason=None):
    return {"job_title": job_title, "company": company, "relevance": relevance, "reason": reason}


# ---------------------------------------------------------------------------
# Empty queue → returns False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_queue_returns_false():
    db = _db_with_job(job_row=None)

    had_work = await score_next_job(db)

    assert had_work is False
    # Only the job SELECT should have been issued — feedback query never reached
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

    # Verify the UPDATE was executed with fit_score (3rd execute call, index 2)
    update_call = db.execute.call_args_list[2]
    params = update_call.args[1]
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

    # job SELECT + feedback SELECT + UPDATE = 3 calls
    assert db.execute.call_count == 3


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

    async def fake_agent(profile, job_postings, **kwargs):
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

    params = db.execute.call_args_list[2].args[1]
    assert json.loads(params["reasons"])  == ["r1"]
    assert json.loads(params["risks"])    == ["risk1"]
    assert json.loads(params["keywords"]) == ["k1", "k2"]


# ---------------------------------------------------------------------------
# Feedback examples — _build_feedback_examples helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_feedback_examples_empty_returns_empty_string():
    db = AsyncMock()
    feedback_result = _feedback_exec([])
    db.execute.return_value = feedback_result

    result = await _build_feedback_examples(db, user_id=1)

    assert result == ""


@pytest.mark.asyncio
async def test_build_feedback_examples_relevant_jobs_included():
    db = AsyncMock()
    db.execute.return_value = _feedback_exec([
        _make_feedback_row("Data Engineer", "ACME", "relevant"),
        _make_feedback_row("ML Engineer",   "Stripe", "relevant"),
    ])

    result = await _build_feedback_examples(db, user_id=1)

    assert "RELEVANT" in result
    assert "Data Engineer at ACME" in result
    assert "ML Engineer at Stripe" in result


@pytest.mark.asyncio
async def test_build_feedback_examples_not_relevant_jobs_included():
    db = AsyncMock()
    db.execute.return_value = _feedback_exec([
        _make_feedback_row("Sales Manager", "Telco Corp", "not_relevant", reason=None),
    ])

    result = await _build_feedback_examples(db, user_id=1)

    assert "NOT RELEVANT" in result
    assert "Sales Manager at Telco Corp" in result


@pytest.mark.asyncio
async def test_build_feedback_examples_reason_included_in_output():
    db = AsyncMock()
    db.execute.return_value = _feedback_exec([
        _make_feedback_row("Sales Manager", "Telco Corp", "not_relevant", reason="Wrong industry"),
    ])

    result = await _build_feedback_examples(db, user_id=1)

    assert "reason: Wrong industry" in result


@pytest.mark.asyncio
async def test_build_feedback_examples_both_groups_included():
    db = AsyncMock()
    db.execute.return_value = _feedback_exec([
        _make_feedback_row("Data Engineer", "ACME",      "relevant"),
        _make_feedback_row("Sales Manager", "Telco Corp", "not_relevant"),
    ])

    result = await _build_feedback_examples(db, user_id=1)

    assert "RELEVANT" in result
    assert "NOT RELEVANT" in result


# ---------------------------------------------------------------------------
# Feedback injected into agent call when present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_feedback_examples_passed_to_agent():
    job_row = _make_job_row()
    db = _db_with_job(job_row, feedback_rows=[
        _make_feedback_row("Data Engineer", "ACME", "relevant"),
    ])

    opp    = _make_opportunity()
    result = _make_research_result(opp)

    captured_kwargs: dict = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured_kwargs.update(kwargs)
        return result, {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_next_job(db)

    assert "feedback_examples" in captured_kwargs
    assert "Data Engineer at ACME" in captured_kwargs["feedback_examples"]


@pytest.mark.asyncio
async def test_no_feedback_passes_empty_string_to_agent():
    job_row = _make_job_row()
    db = _db_with_job(job_row, feedback_rows=[])

    opp    = _make_opportunity()
    result = _make_research_result(opp)

    captured_kwargs: dict = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured_kwargs.update(kwargs)
        return result, {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_next_job(db)

    assert captured_kwargs.get("feedback_examples") == ""


# ---------------------------------------------------------------------------
# full_description=True is passed to the agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_description_flag_passed_to_agent():
    job_row = _make_job_row()
    db = _db_with_job(job_row)

    opp    = _make_opportunity()
    result = _make_research_result(opp)

    captured_kwargs: dict = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured_kwargs.update(kwargs)
        return result, {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_next_job(db)

    assert captured_kwargs.get("full_description") is True


# ---------------------------------------------------------------------------
# scoring_breakdown is JSON-encoded in the UPDATE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scoring_breakdown_json_encoded_in_update():
    job_row = _make_job_row()
    db      = _db_with_job(job_row)

    cat = _make_score_category(category="Technical Skills", jd_experience="Python, SQL",
                                your_profile="Python, PostgreSQL", score=8)
    opp    = _make_opportunity(breakdown=[cat])
    result = _make_research_result(opp)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_job(db)

    params = db.execute.call_args_list[2].args[1]
    breakdown = json.loads(params["breakdown"])
    assert len(breakdown) == 1
    assert breakdown[0]["category"] == "Technical Skills"
    assert breakdown[0]["score"] == 8


@pytest.mark.asyncio
async def test_scoring_breakdown_empty_list_when_not_provided():
    job_row = _make_job_row()
    db      = _db_with_job(job_row)

    opp    = _make_opportunity(breakdown=[])
    result = _make_research_result(opp)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_job(db)

    params = db.execute.call_args_list[2].args[1]
    assert json.loads(params["breakdown"]) == []
