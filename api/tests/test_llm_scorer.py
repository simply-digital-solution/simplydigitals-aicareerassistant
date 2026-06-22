"""
Unit tests for api/app/pipeline/llm_scorer.py

All DB and agent calls are mocked — no live database or LLM needed.

DB execute() call sequence inside score_next_batch:
  1. SELECT job_postings (batch SELECT)
  2. SELECT job_feedback (feedback examples)
  3..N. UPDATE job_postings (one per job in batch)
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.pipeline.llm_scorer import score_next_batch, _build_feedback_examples


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feedback_exec(rows=None):
    """Simulates the job_feedback SELECT."""
    m = MagicMock()
    m.mappings.return_value.all.return_value = rows or []
    return m


def _batch_select_result(job_rows):
    """Simulates the batch job SELECT returning multiple rows."""
    m = MagicMock()
    m.mappings.return_value.all.return_value = job_rows
    return m


def _db_with_batch(job_rows=None, feedback_rows=None):
    """
    Return a mock AsyncSession for a batch of jobs.
    execute() side_effect sequence:
      [0] batch job SELECT
      [1] daily scoring usage check (0 = under limit)
      [2] feedback SELECT
      [3..N] UPDATE per job (only reached when jobs were found)
    """
    db = AsyncMock()
    select_result   = _batch_select_result(job_rows or [])
    usage_result    = MagicMock()
    usage_result.fetchone.return_value = (0,)
    feedback_result = _feedback_exec(feedback_rows)
    update_result   = MagicMock()

    # Provide enough update results for any batch size
    db.execute.side_effect = [select_result, usage_result, feedback_result] + [update_result] * 20
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


def _make_score_row(category="Technical", requirement="Python, SQL",
                    your_profile="Python, PostgreSQL", match="✅ Strong"):
    from app.shared.schemas import ScoreRow
    return ScoreRow(category=category, requirement=requirement,
                    your_profile=your_profile, match=match)


def _make_opportunity(job_id=1, fit_score=0.85, reasons=None, risks=None,
                      keywords=None, breakdown=None, recommendation="Apply — good fit.",
                      industries=None):
    opp = MagicMock()
    opp.job_id              = job_id
    opp.fit_score           = fit_score
    opp.reasons             = reasons  or ["Strong ML skills match"]
    opp.risks               = risks    or ["No Python 3.11 mentioned"]
    opp.key_keywords        = keywords or ["PyTorch", "SQL"]
    opp.scoring_breakdown   = breakdown if breakdown is not None else []
    opp.recommendation      = recommendation
    opp.inferred_industries = industries if industries is not None else ["Technology & Software"]
    return opp


def _make_research_result(opps):
    result = MagicMock()
    result.opportunities = opps if isinstance(opps, list) else [opps]
    return result


def _make_feedback_row(job_title="Data Engineer", company="ACME",
                       relevance="relevant", reason=None):
    return {"job_title": job_title, "company": company,
            "relevance": relevance, "reason": reason}


# ---------------------------------------------------------------------------
# Empty queue → returns False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_queue_returns_false():
    db = _db_with_batch(job_rows=[])

    had_work = await score_next_batch(db)

    assert had_work is False
    db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Happy path: single job batch scored successfully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_score_writes_result():
    job_row = _make_job_row(job_id=1)
    db      = _db_with_batch([job_row])

    opp    = _make_opportunity(job_id=1, fit_score=0.78)
    result = _make_research_result([opp])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        had_work = await score_next_batch(db)

    assert had_work is True
    db.commit.assert_called()

    # UPDATE is call index 3 (0=job SELECT, 1=usage check, 2=feedback SELECT, 3=score write)
    params = db.execute.call_args_list[3].args[1]
    assert params["fit_score"] == 0.78
    assert params["id"] == 1
    update_sql = db.execute.call_args_list[3].args[0].text
    assert "score_error" in update_sql


# ---------------------------------------------------------------------------
# Batch of 3 jobs — all scored, matched by job_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_scores_multiple_jobs():
    rows = [_make_job_row(job_id=i) for i in [10, 20, 30]]
    db   = _db_with_batch(rows)

    opps   = [_make_opportunity(job_id=i, fit_score=round(0.5 + i * 0.01, 2)) for i in [10, 20, 30]]
    result = _make_research_result(opps)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        had_work = await score_next_batch(db)

    assert had_work is True
    # 1 batch SELECT + 1 usage check + 1 feedback SELECT + 3 UPDATEs + 1 increment = 7 execute calls
    assert db.execute.call_count == 7

    scored_ids = {db.execute.call_args_list[i].args[1]["id"] for i in range(3, 6)}
    assert scored_ids == {10, 20, 30}


# ---------------------------------------------------------------------------
# Reordered response — matched correctly by job_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_matches_by_job_id_not_position():
    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    db   = _db_with_batch(rows)

    # LLM returns opportunities in reverse order
    opps   = [_make_opportunity(job_id=2, fit_score=0.9),
              _make_opportunity(job_id=1, fit_score=0.4)]
    result = _make_research_result(opps)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    # job_id=1 should get fit_score=0.4, job_id=2 should get fit_score=0.9
    update_calls = {
        db.execute.call_args_list[i].args[1]["id"]:
        db.execute.call_args_list[i].args[1]["fit_score"]
        for i in range(3, 5)
    }
    assert update_calls[1] == 0.4
    assert update_calls[2] == 0.9


# ---------------------------------------------------------------------------
# Missing job_id in response — marked as failed individually
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_job_id_marked_as_failed():
    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    db   = _db_with_batch(rows)

    # LLM only returns job_id=1, skips job_id=2
    opps   = [_make_opportunity(job_id=1, fit_score=0.75)]
    result = _make_research_result(opps)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    # job_id=1 scored, job_id=2 marked as error
    call_params = [db.execute.call_args_list[i].args[1] for i in range(3, 5)]
    scored   = next(p for p in call_params if p.get("id") == 1)
    failed   = next(p for p in call_params if p.get("id") == 2)
    assert scored["fit_score"] == 0.75
    assert "Missing" in failed["err"]


# ---------------------------------------------------------------------------
# Agent raises exception → all jobs in batch marked failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_exception_marks_all_jobs_failed():
    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    db   = _db_with_batch(rows)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(side_effect=RuntimeError("LLM timed out"))),
    ):
        had_work = await score_next_batch(db)

    assert had_work is True
    db.commit.assert_called()

    # Both jobs should have score_error set
    error_calls = [c for c in db.execute.call_args_list if c.args[1].get("err")]
    assert len(error_calls) == 2
    for call in error_calls:
        params = call.args[1]
        assert "RuntimeError" in params["err"]
        assert "scored=false" in call.args[0].text


# ---------------------------------------------------------------------------
# Agent returns AgentError → all jobs in batch marked failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_error_result_marks_all_jobs_failed():
    from app.shared.schemas import AgentError

    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    db   = _db_with_batch(rows)

    agent_err = AgentError(error="parse failed")

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(return_value=(agent_err, {}))),
    ):
        had_work = await score_next_batch(db)

    assert had_work is True
    error_calls = [c for c in db.execute.call_args_list if c.args[1].get("err")]
    assert len(error_calls) == 2
    for call in error_calls:
        assert call.args[1]["err"] == "parse failed"


# ---------------------------------------------------------------------------
# job_id is passed in each job dict sent to the agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_id_passed_in_job_dicts():
    rows = [_make_job_row(job_id=99), _make_job_row(job_id=100)]
    db   = _db_with_batch(rows)

    captured = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured["job_postings"] = job_postings
        opps = [_make_opportunity(job_id=j["job_id"]) for j in job_postings]
        return _make_research_result(opps), {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_next_batch(db)

    assert [j["job_id"] for j in captured["job_postings"]] == [99, 100]


# ---------------------------------------------------------------------------
# inferred_industries is properly deserialized from JSON string
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inferred_industries_deserialized():
    row = _make_job_row(job_id=1, inferred_industries='["Banking & Financial Services", "FinTech"]')
    db  = _db_with_batch([row])

    captured = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured["industries"] = job_postings[0]["inferred_industries"]
        return _make_research_result([_make_opportunity(job_id=1)]), {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_next_batch(db)

    assert captured["industries"] == ["Banking & Financial Services", "FinTech"]


# ---------------------------------------------------------------------------
# reasons / risks / key_keywords are JSON-encoded in the UPDATE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_fields_json_encoded_in_update():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    opp    = _make_opportunity(job_id=1, reasons=["r1"], risks=["risk1"], keywords=["k1", "k2"])
    result = _make_research_result([opp])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    params = db.execute.call_args_list[3].args[1]
    assert json.loads(params["reasons"])  == ["r1"]
    assert json.loads(params["risks"])    == ["risk1"]
    assert json.loads(params["keywords"]) == ["k1", "k2"]


# ---------------------------------------------------------------------------
# scoring_breakdown is JSON-encoded in the UPDATE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scoring_breakdown_json_encoded_in_update():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    score_row = _make_score_row(category="Technical", requirement="Python, SQL",
                                your_profile="Python, PostgreSQL", match="✅ Strong")
    opp    = _make_opportunity(job_id=1, breakdown=[score_row])
    result = _make_research_result([opp])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    params    = db.execute.call_args_list[3].args[1]
    breakdown = json.loads(params["breakdown"])
    assert len(breakdown) == 1
    assert breakdown[0]["category"]    == "Technical"
    assert breakdown[0]["requirement"] == "Python, SQL"
    assert breakdown[0]["match"]       == "✅ Strong"


@pytest.mark.asyncio
async def test_scoring_breakdown_empty_list_when_not_provided():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    opp    = _make_opportunity(job_id=1, breakdown=[])
    result = _make_research_result([opp])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    params = db.execute.call_args_list[3].args[1]
    assert json.loads(params["breakdown"]) == []


# ---------------------------------------------------------------------------
# recommendation stored in the UPDATE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recommendation_stored_in_update():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    opp    = _make_opportunity(job_id=1, recommendation="Apply — strong match.")
    result = _make_research_result([opp])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    params = db.execute.call_args_list[3].args[1]
    assert params["recommendation"] == "Apply — strong match."


@pytest.mark.asyncio
async def test_empty_recommendation_stored_as_none():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    opp    = _make_opportunity(job_id=1, recommendation="")
    result = _make_research_result([opp])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    params = db.execute.call_args_list[3].args[1]
    assert params["recommendation"] is None


# ---------------------------------------------------------------------------
# inferred_industries written back in UPDATE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inferred_industries_written_in_update():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    opp    = _make_opportunity(job_id=1, industries=["Banking & Financial Services", "Technology & Software"])
    result = _make_research_result([opp])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    params = db.execute.call_args_list[3].args[1]
    assert json.loads(params["industries"]) == ["Banking & Financial Services", "Technology & Software"]


@pytest.mark.asyncio
async def test_empty_inferred_industries_stored_as_empty_list():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    opp    = _make_opportunity(job_id=1, industries=[])
    result = _make_research_result([opp])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    params = db.execute.call_args_list[3].args[1]
    assert json.loads(params["industries"]) == []


# ---------------------------------------------------------------------------
# scored_by_model written to DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scored_by_model_written_from_meta():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    opp    = _make_opportunity(job_id=1)
    result = _make_research_result([opp])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(return_value=(result, {"model": "gemini-flash-latest"}))),
    ):
        await score_next_batch(db)

    params = db.execute.call_args_list[3].args[1]
    assert params["model"] == "gemini-flash-latest"


@pytest.mark.asyncio
async def test_scored_by_model_none_when_meta_missing():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    opp    = _make_opportunity(job_id=1)
    result = _make_research_result([opp])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    params = db.execute.call_args_list[3].args[1]
    assert params["model"] is None


# ---------------------------------------------------------------------------
# Feedback examples — _build_feedback_examples helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_feedback_examples_empty_returns_empty_string():
    db = AsyncMock()
    db.execute.return_value = _feedback_exec([])
    assert await _build_feedback_examples(db, user_id=1) == ""


@pytest.mark.asyncio
async def test_build_feedback_examples_relevant_jobs_included():
    db = AsyncMock()
    db.execute.return_value = _feedback_exec([
        _make_feedback_row("Data Engineer", "ACME",   "relevant"),
        _make_feedback_row("ML Engineer",  "Stripe",  "relevant"),
    ])
    result = await _build_feedback_examples(db, user_id=1)
    assert "RELEVANT" in result
    assert "Data Engineer at ACME" in result
    assert "ML Engineer at Stripe" in result


@pytest.mark.asyncio
async def test_build_feedback_examples_not_relevant_jobs_included():
    db = AsyncMock()
    db.execute.return_value = _feedback_exec([
        _make_feedback_row("Sales Manager", "Telco Corp", "not_relevant"),
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
        _make_feedback_row("Data Engineer", "ACME",       "relevant"),
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
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row], feedback_rows=[
        _make_feedback_row("Data Engineer", "ACME", "relevant"),
    ])

    captured: dict = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured.update(kwargs)
        return _make_research_result([_make_opportunity(job_id=1)]), {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_next_batch(db)

    assert "feedback_examples" in captured
    assert "Data Engineer at ACME" in captured["feedback_examples"]


@pytest.mark.asyncio
async def test_no_feedback_passes_empty_string_to_agent():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row], feedback_rows=[])

    captured: dict = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured.update(kwargs)
        return _make_research_result([_make_opportunity(job_id=1)]), {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_next_batch(db)

    assert captured.get("feedback_examples") == ""


# ---------------------------------------------------------------------------
# full_description=True is passed to the agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_description_flag_passed_to_agent():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    captured: dict = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured.update(kwargs)
        return _make_research_result([_make_opportunity(job_id=1)]), {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_next_batch(db)

    assert captured.get("full_description") is True


# ---------------------------------------------------------------------------
# Retry logic — failure path stamps scored_at so the 30-min clock starts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exception_failure_stamps_scored_at():
    rows = [_make_job_row(job_id=1)]
    db   = _db_with_batch(rows)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(side_effect=RuntimeError("timeout"))),
    ):
        await score_next_batch(db)

    update_call = db.execute.call_args_list[3]
    sql    = update_call.args[0].text
    params = update_call.args[1]
    assert "scored_at" in sql
    assert params.get("now") is not None


@pytest.mark.asyncio
async def test_agent_error_failure_stamps_scored_at():
    from app.shared.schemas import AgentError
    rows = [_make_job_row(job_id=1)]
    db   = _db_with_batch(rows)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(return_value=(AgentError(error="parse failed"), {}))),
    ):
        await score_next_batch(db)

    update_call = db.execute.call_args_list[3]
    sql    = update_call.args[0].text
    params = update_call.args[1]
    assert "scored_at" in sql
    assert params.get("now") is not None


@pytest.mark.asyncio
async def test_missing_job_stamps_scored_at():
    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    db   = _db_with_batch(rows)

    # LLM returns only job 1; job 2 is missing
    opps   = [_make_opportunity(job_id=1)]
    result = _make_research_result(opps)

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    # Find the failure UPDATE (has an "err" param and "scored_at")
    failure_calls = [c for c in db.execute.call_args_list if c.args[1].get("err")]
    assert len(failure_calls) == 1
    assert "scored_at" in failure_calls[0].args[0].text
    assert failure_calls[0].args[1].get("now") is not None


# ---------------------------------------------------------------------------
# Retry loop query — picks up errored jobs after 30-min cooldown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_query_includes_errored_jobs_with_old_scored_at():
    """The SELECT WHERE clause must include score_error IS NOT NULL with cooldown."""
    db = _db_with_batch(job_rows=[])

    await score_next_batch(db)

    select_sql = db.execute.call_args_list[0].args[0].text
    assert "score_error IS NULL" in select_sql
    # Also retries errored jobs after cooldown
    assert "scored_at" in select_sql
    assert "30 minutes" in select_sql


@pytest.mark.asyncio
async def test_loop_query_excludes_jobs_currently_rescoring():
    """Jobs with rescoring=true must not be picked up by the loop."""
    db = _db_with_batch(job_rows=[])

    await score_next_batch(db)

    select_sql = db.execute.call_args_list[0].args[0].text
    assert "rescoring = false" in select_sql


@pytest.mark.asyncio
async def test_loop_query_excludes_applied_or_advanced_status_jobs():
    """Loop SELECT must filter out jobs whose application is applied/interviewing/etc."""
    db = _db_with_batch(job_rows=[])

    await score_next_batch(db)

    select_sql = db.execute.call_args_list[0].args[0].text
    assert "NOT EXISTS" in select_sql
    assert "applied" in select_sql
    assert "interviewing" in select_sql
