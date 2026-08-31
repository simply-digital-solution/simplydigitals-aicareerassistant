"""
Tests for scripts/score_idle_jobs.py's score_all_idle_jobs() loop.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest


def _make_get_db_context():
    @asynccontextmanager
    async def get_db_context():
        yield AsyncMock()
    return get_db_context


@pytest.mark.asyncio
async def test_stops_immediately_when_queue_empty():
    with patch("scripts.score_idle_jobs.score_next_batch", AsyncMock(return_value=False)), \
         patch("scripts.score_idle_jobs.get_db_context", _make_get_db_context()):
        from scripts.score_idle_jobs import score_all_idle_jobs
        scored = await score_all_idle_jobs()

    assert scored == 0


@pytest.mark.asyncio
async def test_counts_each_scored_job_until_queue_empty():
    results = [True, True, True, False]

    async def _next_result(db):
        return results.pop(0)

    with patch("scripts.score_idle_jobs.score_next_batch", side_effect=_next_result), \
         patch("scripts.score_idle_jobs.get_db_context", _make_get_db_context()):
        from scripts.score_idle_jobs import score_all_idle_jobs
        scored = await score_all_idle_jobs()

    assert scored == 3
