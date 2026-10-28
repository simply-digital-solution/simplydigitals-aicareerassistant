"""
Tests for scripts/score_idle_jobs.py's score_all_idle_jobs() loop and its
end-of-run failure summary.
"""
from contextlib import asynccontextmanager
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

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


# ---------------------------------------------------------------------------
# _find_failures_since / main() — end-of-run failure summary
# ---------------------------------------------------------------------------

def _make_failures_db(rows):
    db = AsyncMock()
    result = MagicMock()
    result.mappings.return_value = rows
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_find_failures_since_returns_rows():
    from datetime import datetime
    failure_row = {"title": "Delivery Manager", "company": "Acme", "score_error": "402 Payment Required"}

    @asynccontextmanager
    async def get_db_context():
        yield _make_failures_db([failure_row])

    with patch("scripts.score_idle_jobs.get_db_context", get_db_context):
        from scripts.score_idle_jobs import _find_failures_since
        failures = await _find_failures_since(datetime.now(UTC))

    assert failures == [failure_row]


@pytest.mark.asyncio
async def test_main_prints_pipeline_error_marker_when_jobs_failed(capsys):

    with patch("scripts.score_idle_jobs.score_all_idle_jobs", AsyncMock(return_value=0)), \
         patch("scripts.score_idle_jobs._find_failures_since", AsyncMock(return_value=[
             {"title": "Delivery Manager", "company": "Acme", "score_error": "402 Payment Required"},
         ])):
        from scripts.score_idle_jobs import main
        await main()

    out = capsys.readouterr().out
    assert "PIPELINE_ERROR:" in out
    assert "Delivery Manager" in out
    assert "402 Payment Required" in out


@pytest.mark.asyncio
async def test_main_prints_no_error_block_when_nothing_failed(capsys):
    with patch("scripts.score_idle_jobs.score_all_idle_jobs", AsyncMock(return_value=2)), \
         patch("scripts.score_idle_jobs._find_failures_since", AsyncMock(return_value=[])):
        from scripts.score_idle_jobs import main
        await main()

    out = capsys.readouterr().out
    assert "PIPELINE_ERROR:" not in out
