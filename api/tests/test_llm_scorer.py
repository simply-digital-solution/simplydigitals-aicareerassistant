"""
Unit tests for api/app/pipeline/llm_scorer.py

All DB and agent calls are mocked — no live database or LLM needed.

DB execute() call sequence inside score_next_batch:
  1. SELECT from user_job_postings JOIN job_postings (LIMIT 1)
  2. SELECT lifetime SUM (_get_daily_limit)
  3. SELECT daily_scoring_usage today (_get_scorings_today)
  4. SELECT job_feedback (feedback examples)
  5. UPDATE user_job_postings (score write, via _write_score)
  6. UPDATE job_postings inferred_industries
  7. INSERT daily_scoring_usage (increment counter)
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
      [0] batch job SELECT (returns jp_id, user_id, ...)
      [1] lifetime SUM check (_get_daily_limit)
      [2] daily scoring usage check today (_get_scorings_today)
      [3] feedback SELECT
      [4..N] UPDATE user_job_postings per job (score write)
      [N+1..M] UPDATE job_postings inferred_industries
      [last] INSERT daily_scoring_usage increment
    """
    db = AsyncMock()
    select_result    = _batch_select_result(job_rows or [])
    lifetime_result  = MagicMock()
    lifetime_result.fetchone.return_value = (100,)  # existing user → 50 limit
    usage_result     = MagicMock()
    usage_result.fetchone.return_value = (0,)
    feedback_result  = _feedback_exec(feedback_rows)
    update_result    = MagicMock()

    # Provide enough update results for any batch size (2 updates per job + increment)
    db.execute.side_effect = [select_result, lifetime_result, usage_result, feedback_result] + [update_result] * 40
    return db


def _make_job_row(job_id=1, user_id=42,
                  title="ML Engineer", company="DeepCo",
                  url="https://www.mycareersfuture.gov.sg/job/xyz",
                  description="Build ML models",
                  inferred_industries='["Technology & Software"]'):
    # New schema: jp_id (job_postings.id), user_id
    return {
        "jp_id":               job_id,
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


def _find_ujp_update_calls(db):
    """Return execute calls that UPDATE user_job_postings with a score."""
    return [c for c in db.execute.call_args_list
            if "UPDATE user_job_postings" in c.args[0].text
            and c.args[1].get("fit_score") is not None]


def _find_error_calls(db):
    """Return execute calls that set score_error on user_job_postings."""
    return [c for c in db.execute.call_args_list if c.args[1].get("err")]


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

    # Find the score write UPDATE
    score_calls = _find_ujp_update_calls(db)
    assert len(score_calls) == 1
    params = score_calls[0].args[1]
    assert params["fit_score"] == 0.78
    assert params["jid"] == 1
    assert "score_error" in score_calls[0].args[0].text


# ---------------------------------------------------------------------------
# Only one job fetched per call (LIMIT 1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scores_exactly_one_job_per_call():
    """score_next_batch fetches and scores exactly 1 job per invocation."""
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    opp    = _make_opportunity(job_id=1, fit_score=0.78)
    result = _make_research_result([opp])

    captured: dict = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured["job_postings"] = job_postings
        return _make_research_result([_make_opportunity(job_id=job_postings[0]["job_id"])]), {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_next_batch(db)

    assert len(captured["job_postings"]) == 1
    assert captured["job_postings"][0]["job_id"] == 1


@pytest.mark.asyncio
async def test_select_query_uses_limit_1():
    """The SELECT must use LIMIT 1 — single job per call."""
    db = _db_with_batch(job_rows=[])
    await score_next_batch(db)
    select_sql = db.execute.call_args_list[0].args[0].text
    assert "LIMIT 1" in select_sql


# ---------------------------------------------------------------------------
# Missing job_id in response — single job marked as failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_job_id_marked_as_failed():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    # LLM returns wrong job_id
    result = _make_research_result([_make_opportunity(job_id=999)])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    error_calls = _find_error_calls(db)
    assert len(error_calls) == 1
    assert "Missing" in error_calls[0].args[1]["err"]
    assert "rescoring=false" in error_calls[0].args[0].text


# ---------------------------------------------------------------------------
# Agent raises exception → job marked failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_exception_marks_job_failed():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(side_effect=RuntimeError("LLM timed out"))),
    ):
        had_work = await score_next_batch(db)

    assert had_work is True
    db.commit.assert_called()
    error_calls = _find_error_calls(db)
    assert len(error_calls) == 1
    assert "RuntimeError" in error_calls[0].args[1]["err"]
    assert "scored=false" in error_calls[0].args[0].text
    assert "rescoring=false" in error_calls[0].args[0].text


# ---------------------------------------------------------------------------
# Agent returns AgentError → job marked failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_error_result_marks_job_failed():
    from app.shared.schemas import AgentError

    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent",
              AsyncMock(return_value=(AgentError(error="parse failed"), {}))),
    ):
        had_work = await score_next_batch(db)

    assert had_work is True
    error_calls = _find_error_calls(db)
    assert len(error_calls) == 1
    assert error_calls[0].args[1]["err"] == "parse failed"
    assert "rescoring=false" in error_calls[0].args[0].text


# ---------------------------------------------------------------------------
# job_id is passed in the job dict sent to the agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_id_passed_in_job_dict():
    row = _make_job_row(job_id=99)
    db  = _db_with_batch([row])

    captured = {}

    async def fake_agent(profile, job_postings, **kwargs):
        captured["job_postings"] = job_postings
        return _make_research_result([_make_opportunity(job_id=99)]), {}

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", fake_agent),
    ):
        await score_next_batch(db)

    assert captured["job_postings"][0]["job_id"] == 99


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

    params = _find_ujp_update_calls(db)[0].args[1]
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

    params    = _find_ujp_update_calls(db)[0].args[1]
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

    params = _find_ujp_update_calls(db)[0].args[1]
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

    params = _find_ujp_update_calls(db)[0].args[1]
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

    params = _find_ujp_update_calls(db)[0].args[1]
    assert params["recommendation"] is None


# ---------------------------------------------------------------------------
# inferred_industries written back to job_postings (shared table)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inferred_industries_written_to_job_postings():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    opp    = _make_opportunity(job_id=1, industries=["Banking & Financial Services", "Technology & Software"])
    result = _make_research_result([opp])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    # Find the job_postings inferred_industries update
    ind_calls = [c for c in db.execute.call_args_list
                 if "UPDATE job_postings" in c.args[0].text
                 and "inferred_industries" in c.args[0].text]
    assert len(ind_calls) == 1
    assert json.loads(ind_calls[0].args[1]["ind"]) == ["Banking & Financial Services", "Technology & Software"]


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

    ind_calls = [c for c in db.execute.call_args_list
                 if "UPDATE job_postings" in c.args[0].text
                 and "inferred_industries" in c.args[0].text]
    assert len(ind_calls) == 1
    assert json.loads(ind_calls[0].args[1]["ind"]) == []


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

    params = _find_ujp_update_calls(db)[0].args[1]
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

    params = _find_ujp_update_calls(db)[0].args[1]
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

    error_calls = _find_error_calls(db)
    assert len(error_calls) == 1
    sql    = error_calls[0].args[0].text
    params = error_calls[0].args[1]
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

    error_calls = _find_error_calls(db)
    assert len(error_calls) == 1
    sql    = error_calls[0].args[0].text
    params = error_calls[0].args[1]
    assert "scored_at" in sql
    assert params.get("now") is not None


@pytest.mark.asyncio
async def test_missing_job_stamps_scored_at():
    row = _make_job_row(job_id=1)
    db  = _db_with_batch([row])

    # LLM returns wrong job_id — job 1 goes missing
    result = _make_research_result([_make_opportunity(job_id=999)])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await score_next_batch(db)

    error_calls = _find_error_calls(db)
    assert len(error_calls) == 1
    assert "scored_at" in error_calls[0].args[0].text
    assert error_calls[0].args[1].get("now") is not None


# ---------------------------------------------------------------------------
# Retry loop query — picks up errored jobs after 30-min cooldown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loop_query_includes_errored_jobs_with_old_scored_at():
    """The SELECT WHERE clause must include score_error IS NULL with cooldown."""
    db = _db_with_batch(job_rows=[])

    await score_next_batch(db)

    select_sql = db.execute.call_args_list[0].args[0].text
    assert "score_error IS NULL" in select_sql
    assert "scored_at" in select_sql
    assert "30 minutes" in select_sql


@pytest.mark.asyncio
async def test_loop_query_picks_up_pending_rescores():
    """Jobs with scored=true AND rescoring=true (pending rescore) must be picked up by the loop."""
    db = _db_with_batch(job_rows=[])

    await score_next_batch(db)

    select_sql = db.execute.call_args_list[0].args[0].text
    # Both new unscored jobs and pending rescores are included
    assert "scored = false AND ujp.rescoring = false" in select_sql
    assert "scored = true AND ujp.rescoring = true" in select_sql


@pytest.mark.asyncio
async def test_loop_query_excludes_applied_or_advanced_status_jobs():
    """Loop SELECT must filter out jobs whose application is applied/interviewing/etc."""
    db = _db_with_batch(job_rows=[])

    await score_next_batch(db)

    select_sql = db.execute.call_args_list[0].args[0].text
    assert "NOT EXISTS" in select_sql
    assert "applied" in select_sql
    assert "interviewing" in select_sql


# ---------------------------------------------------------------------------
# Release 4 — dual-path: controller enqueue when flag on
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_off_uses_direct_path():
    """Positive: flag off → run_research_agent is called directly (no controller)."""
    row    = _make_job_row(job_id=10)
    db     = _db_with_batch([row])
    opp    = _make_opportunity(job_id=10)
    result = _make_research_result([opp])

    mock_agent = AsyncMock(return_value=(result, {"model": "gemini-2.5-flash-lite"}))
    mock_settings = MagicMock()
    mock_settings.enable_llm_traffic_controller = False
    mock_settings.max_scorings_per_user_per_day = 50
    mock_settings.new_user_scoring_limit = 250

    with (
        patch("app.pipeline.llm_scorer.get_settings", return_value=mock_settings),
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", mock_agent),
    ):
        had_work = await score_next_batch(db)

    assert had_work is True
    mock_agent.assert_called_once()


@pytest.mark.asyncio
async def test_flag_on_enqueues_to_controller_not_direct_agent():
    """Positive: flag on → enqueue() is called, run_research_agent is NOT called."""
    row = _make_job_row(job_id=20, user_id=5)
    db  = _db_with_batch([row])

    mock_controller = MagicMock()
    mock_controller.enqueue.return_value = True
    mock_controller.queue_size = 1

    mock_settings = MagicMock()
    mock_settings.enable_llm_traffic_controller = True
    mock_settings.max_scorings_per_user_per_day = 50
    mock_settings.new_user_scoring_limit = 250

    mock_agent = AsyncMock()

    with (
        patch("app.pipeline.llm_scorer.get_settings", return_value=mock_settings),
        patch("app.pipeline.llm_scorer.run_research_agent", mock_agent),
        patch("app.shared.llm_traffic_controller.get_controller", return_value=mock_controller),
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
    ):
        had_work = await score_next_batch(db)

    assert had_work is True
    mock_controller.enqueue.assert_called_once_with(user_id=5, job_id=20)
    mock_agent.assert_not_called()


@pytest.mark.asyncio
async def test_flag_on_enqueue_passes_correct_user_and_job():
    """Positive: enqueue receives the exact user_id and job_id from the SELECT result."""
    row = _make_job_row(job_id=77, user_id=99)
    db  = _db_with_batch([row])

    mock_controller = MagicMock()
    mock_controller.enqueue.return_value = True
    mock_controller.queue_size = 1

    mock_settings = MagicMock()
    mock_settings.enable_llm_traffic_controller = True
    mock_settings.max_scorings_per_user_per_day = 50
    mock_settings.new_user_scoring_limit = 250

    with (
        patch("app.pipeline.llm_scorer.get_settings", return_value=mock_settings),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock()),
        patch("app.shared.llm_traffic_controller.get_controller", return_value=mock_controller),
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
    ):
        await score_next_batch(db)

    mock_controller.enqueue.assert_called_once_with(user_id=99, job_id=77)


@pytest.mark.asyncio
async def test_flag_on_queue_full_still_returns_true():
    """Negative: controller returns False (queue full) — score_next_batch still returns True (job was found)."""
    row = _make_job_row(job_id=30, user_id=5)
    db  = _db_with_batch([row])

    mock_controller = MagicMock()
    mock_controller.enqueue.return_value = False  # queue full
    mock_controller.queue_size = 500

    mock_settings = MagicMock()
    mock_settings.enable_llm_traffic_controller = True
    mock_settings.max_scorings_per_user_per_day = 50
    mock_settings.new_user_scoring_limit = 250

    with (
        patch("app.pipeline.llm_scorer.get_settings", return_value=mock_settings),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock()),
        patch("app.shared.llm_traffic_controller.get_controller", return_value=mock_controller),
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
    ):
        had_work = await score_next_batch(db)

    assert had_work is True


@pytest.mark.asyncio
async def test_flag_on_controller_none_falls_back_to_direct_path():
    """Negative: flag on but controller not initialised → falls back to direct agent call."""
    row    = _make_job_row(job_id=40)
    db     = _db_with_batch([row])
    opp    = _make_opportunity(job_id=40)
    result = _make_research_result([opp])

    mock_settings = MagicMock()
    mock_settings.enable_llm_traffic_controller = True
    mock_settings.max_scorings_per_user_per_day = 50
    mock_settings.new_user_scoring_limit = 250

    mock_agent = AsyncMock(return_value=(result, {"model": "gemini-2.5-flash-lite"}))

    with (
        patch("app.pipeline.llm_scorer.get_settings", return_value=mock_settings),
        patch("app.pipeline.llm_scorer.run_research_agent", mock_agent),
        patch("app.shared.llm_traffic_controller.get_controller", return_value=None),
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
    ):
        had_work = await score_next_batch(db)

    assert had_work is True
    mock_agent.assert_called_once()


@pytest.mark.asyncio
async def test_empty_queue_returns_false_regardless_of_flag():
    """Negative: empty queue always returns False regardless of which path is active."""
    db = _db_with_batch(job_rows=[])

    for flag in (True, False):
        db.execute.reset_mock()
        db.execute.side_effect = [_batch_select_result([])]

        mock_settings = MagicMock()
        mock_settings.enable_llm_traffic_controller = flag
        mock_settings.max_scorings_per_user_per_day = 50
        mock_settings.new_user_scoring_limit = 250

        with patch("app.pipeline.llm_scorer.get_settings", return_value=mock_settings):
            had_work = await score_next_batch(db)

        assert had_work is False, f"Expected False when flag={flag} and queue empty"
