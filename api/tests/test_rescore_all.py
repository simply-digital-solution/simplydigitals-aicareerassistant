"""
Unit tests for POST /research/jobs/rescore-all
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


async def _call_rescore_all(db, user_id=1):
    from app.modules.agents.router import rescore_all_jobs
    user = MagicMock()
    user.id = user_id
    return await rescore_all_jobs(current_user=user, db=db)


def _make_db(job_ids=None):
    db = AsyncMock()
    select_result = MagicMock()
    select_result.fetchall.return_value = [(jid,) for jid in (job_ids or [])]
    reset_result = MagicMock()
    db.execute.side_effect = [select_result, reset_result]
    return db


# ---------------------------------------------------------------------------
# No jobs → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_jobs_raises_404():
    db = _make_db(job_ids=[])
    with pytest.raises(HTTPException) as exc:
        await _call_rescore_all(db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Happy path — returns count of jobs rescored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_count():
    db = _make_db(job_ids=[1, 2, 3])
    with patch("app.pipeline.llm_scorer.score_jobs_by_ids", AsyncMock(return_value={1: True, 2: True, 3: True})):
        result = await _call_rescore_all(db)
    assert result["count"] == 3


# ---------------------------------------------------------------------------
# Reset is called before scoring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_called_before_score():
    db = _make_db(job_ids=[1, 2])
    with patch("app.pipeline.llm_scorer.score_jobs_by_ids", AsyncMock(return_value={})):
        await _call_rescore_all(db)

    reset_sql = db.execute.call_args_list[1].args[0].text
    assert "scored = 0" in reset_sql
    assert "fit_score = NULL" in reset_sql
    assert "archived = 0" in reset_sql


# ---------------------------------------------------------------------------
# Only unarchived jobs are included
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_unarchived_queried():
    db = _make_db(job_ids=[5, 6])
    with patch("app.pipeline.llm_scorer.score_jobs_by_ids", AsyncMock(return_value={})):
        await _call_rescore_all(db)

    select_sql = db.execute.call_args_list[0].args[0].text
    assert "archived = 0" in select_sql
