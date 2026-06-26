"""
Unit tests for score_jobs_by_ids() in llm_scorer.py

score_jobs_by_ids() now delegates to score_single_job() for each job_id,
so tests mock score_single_job directly.
"""
from unittest.mock import AsyncMock, patch
import pytest

from app.pipeline.llm_scorer import score_jobs_by_ids


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
# All jobs scored successfully → all True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_jobs_scored_returns_true():
    db = AsyncMock()
    with patch("app.pipeline.llm_scorer.score_single_job", AsyncMock(return_value=True)):
        result = await score_jobs_by_ids(db, [1, 2, 3])
    assert result == {1: True, 2: True, 3: True}


# ---------------------------------------------------------------------------
# All jobs fail → all False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_jobs_failed_returns_false():
    db = AsyncMock()
    with patch("app.pipeline.llm_scorer.score_single_job", AsyncMock(return_value=False)):
        result = await score_jobs_by_ids(db, [1, 2])
    assert result == {1: False, 2: False}


# ---------------------------------------------------------------------------
# Partial success — each job scored independently
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partial_success_tracked_per_job():
    db = AsyncMock()
    side_effects = [True, False, True]
    with patch("app.pipeline.llm_scorer.score_single_job", AsyncMock(side_effect=side_effects)):
        result = await score_jobs_by_ids(db, [10, 20, 30])
    assert result == {10: True, 20: False, 30: True}


# ---------------------------------------------------------------------------
# score_single_job called once per job_id with correct args
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_single_job_called_for_each_id():
    db = AsyncMock()
    mock_single = AsyncMock(return_value=True)
    with patch("app.pipeline.llm_scorer.score_single_job", mock_single):
        await score_jobs_by_ids(db, [5, 6], user_id=42)

    assert mock_single.call_count == 2
    calls = mock_single.call_args_list
    assert calls[0].args == (db, 5)
    assert calls[0].kwargs == {"user_id": 42}
    assert calls[1].args == (db, 6)
    assert calls[1].kwargs == {"user_id": 42}


# ---------------------------------------------------------------------------
# user_id=None passed through correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_id_none_passed_through():
    db = AsyncMock()
    mock_single = AsyncMock(return_value=True)
    with patch("app.pipeline.llm_scorer.score_single_job", mock_single):
        await score_jobs_by_ids(db, [7], user_id=None)

    mock_single.assert_called_once_with(db, 7, user_id=None)


# ---------------------------------------------------------------------------
# Single job scored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_job_scored():
    db = AsyncMock()
    with patch("app.pipeline.llm_scorer.score_single_job", AsyncMock(return_value=True)):
        result = await score_jobs_by_ids(db, [99])
    assert result == {99: True}
