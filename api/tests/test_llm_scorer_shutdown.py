"""
Tests for graceful shutdown behaviour of run_scorer_loop().

Verifies:
1. Loop exits without doing any work when shutdown_event is pre-set.
2. An in-flight job runs to completion before the loop exits.
3. A shutdown signal during the idle sleep wakes the loop immediately.
"""
import asyncio
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest


def _make_get_db_fn():
    """Returns a get_db_fn that yields a fresh AsyncMock each call."""
    @asynccontextmanager
    async def get_db_fn():
        yield AsyncMock()
    return get_db_fn


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_exits_immediately_when_event_preset():
    """Loop should not call score_next_batch at all if shutdown is already set."""
    event = asyncio.Event()
    event.set()

    with patch("app.pipeline.llm_scorer.score_next_batch", AsyncMock(return_value=False)) as mock_score:
        from app.pipeline.llm_scorer import run_scorer_loop
        await run_scorer_loop(_make_get_db_fn(), event)

    mock_score.assert_not_called()


@pytest.mark.asyncio
async def test_loop_finishes_current_job_before_exiting():
    """
    When shutdown is signalled while a job is being scored, the current
    score_next_batch() call must complete (return True) before the loop exits.
    """
    event = asyncio.Event()
    completed_jobs: list[int] = []

    async def _score_one(db):
        completed_jobs.append(1)
        # Signal shutdown mid-job — loop must still finish this call
        event.set()
        return True

    with patch("app.pipeline.llm_scorer.score_next_batch", side_effect=_score_one):
        from app.pipeline.llm_scorer import run_scorer_loop
        await run_scorer_loop(_make_get_db_fn(), event)

    assert len(completed_jobs) == 1, "job must complete before loop exits"


@pytest.mark.asyncio
async def test_idle_sleep_interrupted_by_shutdown():
    """
    When the queue is empty the loop sleeps SLEEP_QUEUE_EMPTY (300s).
    A shutdown signal must wake it in well under 1 second.
    """
    event = asyncio.Event()

    async def _empty_queue(db):
        return False  # no work — triggers long idle sleep

    async def _signal_after_delay():
        await asyncio.sleep(0.05)
        event.set()

    with patch("app.pipeline.llm_scorer.score_next_batch", side_effect=_empty_queue):
        from app.pipeline.llm_scorer import run_scorer_loop
        asyncio.create_task(_signal_after_delay())
        t0 = time.monotonic()
        await run_scorer_loop(_make_get_db_fn(), event)
        elapsed = time.monotonic() - t0

    assert elapsed < 2.0, f"loop should exit quickly on shutdown signal, took {elapsed:.2f}s"
