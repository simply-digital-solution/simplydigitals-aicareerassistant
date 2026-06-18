"""
Unit tests for api/app/pipeline/industry_backfill.py
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.pipeline.industry_backfill import backfill_industries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(job_rows=None):
    db = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = job_rows or []
    update_result = MagicMock()
    db.execute.side_effect = [select_result] + [update_result] * 50
    return db


def _make_job_row(job_id=1, title="Software Engineer", company="TechCo", description="Build APIs"):
    return {"id": job_id, "title": title, "company": company, "description": description}


def _make_classification(job_id, industries):
    c = MagicMock()
    c.job_id = job_id
    c.industries = industries
    return c


def _make_result(classifications):
    result = MagicMock()
    result.classifications = classifications
    return result


# ---------------------------------------------------------------------------
# Empty queue — no LLM call, returns 0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_queue_returns_zero():
    db = _make_db(job_rows=[])

    with patch("app.pipeline.industry_backfill.get_llm_client") as mock_client:
        count = await backfill_industries(db)

    assert count == 0
    mock_client.assert_not_called()


# ---------------------------------------------------------------------------
# Single job classified successfully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_job_classified():
    db = _make_db([_make_job_row(job_id=1)])

    classification = _make_classification(1, ["Technology & Software"])
    result = _make_result([classification])

    mock_llm = AsyncMock()
    mock_llm.run_agent = AsyncMock(return_value=(result, {}))

    with patch("app.pipeline.industry_backfill.get_llm_client", return_value=mock_llm):
        count = await backfill_industries(db)

    assert count == 1
    db.commit.assert_called()

    update_params = db.execute.call_args_list[1].args[1]
    assert json.loads(update_params["ind"]) == ["Technology & Software"]
    assert update_params["id"] == 1


# ---------------------------------------------------------------------------
# Multiple jobs — all classified
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_jobs_all_classified():
    rows = [_make_job_row(job_id=i) for i in [10, 20, 30]]
    db = _make_db(rows)

    classifications = [
        _make_classification(10, ["Technology & Software"]),
        _make_classification(20, ["Banking & Financial Services"]),
        _make_classification(30, ["Consulting & Professional Services"]),
    ]
    result = _make_result(classifications)

    mock_llm = AsyncMock()
    mock_llm.run_agent = AsyncMock(return_value=(result, {}))

    with patch("app.pipeline.industry_backfill.get_llm_client", return_value=mock_llm):
        count = await backfill_industries(db)

    assert count == 3
    # 1 SELECT + 3 UPDATEs
    assert db.execute.call_count == 4


# ---------------------------------------------------------------------------
# Missing job_id in response — skipped, others still classified
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_job_id_skipped():
    rows = [_make_job_row(job_id=1), _make_job_row(job_id=2)]
    db = _make_db(rows)

    # LLM returns only job_id=1
    result = _make_result([_make_classification(1, ["Technology & Software"])])

    mock_llm = AsyncMock()
    mock_llm.run_agent = AsyncMock(return_value=(result, {}))

    with patch("app.pipeline.industry_backfill.get_llm_client", return_value=mock_llm):
        count = await backfill_industries(db)

    assert count == 1
    # 1 SELECT + 1 UPDATE (only job_id=1)
    assert db.execute.call_count == 2


# ---------------------------------------------------------------------------
# Agent returns AgentError — batch skipped, no updates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_error_skips_batch():
    from app.shared.schemas import AgentError
    db = _make_db([_make_job_row(job_id=1)])

    mock_llm = AsyncMock()
    mock_llm.run_agent = AsyncMock(return_value=(AgentError(error="parse failed"), {}))

    with patch("app.pipeline.industry_backfill.get_llm_client", return_value=mock_llm):
        count = await backfill_industries(db)

    assert count == 0
    # Only the SELECT was called — no UPDATE
    assert db.execute.call_count == 1


# ---------------------------------------------------------------------------
# Agent raises exception — batch skipped, no updates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_exception_skips_batch():
    db = _make_db([_make_job_row(job_id=1)])

    mock_llm = AsyncMock()
    mock_llm.run_agent = AsyncMock(side_effect=RuntimeError("timeout"))

    with patch("app.pipeline.industry_backfill.get_llm_client", return_value=mock_llm):
        count = await backfill_industries(db)

    assert count == 0
    assert db.execute.call_count == 1


# ---------------------------------------------------------------------------
# Empty industries list stored correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_industries_stored_as_empty_list():
    db = _make_db([_make_job_row(job_id=1)])

    result = _make_result([_make_classification(1, [])])
    mock_llm = AsyncMock()
    mock_llm.run_agent = AsyncMock(return_value=(result, {}))

    with patch("app.pipeline.industry_backfill.get_llm_client", return_value=mock_llm):
        count = await backfill_industries(db)

    assert count == 1
    update_params = db.execute.call_args_list[1].args[1]
    assert json.loads(update_params["ind"]) == []


# ---------------------------------------------------------------------------
# Module is importable as CLI entrypoint
# ---------------------------------------------------------------------------

def test_module_has_main_entrypoint():
    import app.pipeline.industry_backfill as m
    assert hasattr(m, "_main")
    assert hasattr(m, "backfill_industries")
