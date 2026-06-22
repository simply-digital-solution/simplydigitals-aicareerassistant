"""
Unit tests for POST /research/jobs/rescore-all
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
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
    db.execute.side_effect = [select_result]
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
# Happy path — returns count of all jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_count():
    db = _make_db(job_ids=[1, 2, 3])
    with patch("app.pipeline.llm_scorer.score_jobs_by_ids", AsyncMock(return_value={1: True, 2: True, 3: True})):
        result = await _call_rescore_all(db)
    assert result["count"] == 3


# ---------------------------------------------------------------------------
# No pre-reset — old scores preserved until new ones arrive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_pre_reset_before_score():
    db = _make_db(job_ids=[1, 2])
    with patch("app.pipeline.llm_scorer.score_jobs_by_ids", AsyncMock(return_value={})):
        await _call_rescore_all(db)

    # Only 1 execute call — the initial SELECT; no destructive reset
    assert db.execute.call_count == 1
    select_sql = db.execute.call_args_list[0].args[0].text
    assert "scored = 0" not in select_sql
    assert "fit_score = NULL" not in select_sql


# ---------------------------------------------------------------------------
# Only unarchived jobs are included
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_unarchived_queried():
    db = _make_db(job_ids=[5, 6])
    with patch("app.pipeline.llm_scorer.score_jobs_by_ids", AsyncMock(return_value={})):
        await _call_rescore_all(db)

    select_sql = db.execute.call_args_list[0].args[0].text
    assert "archived = false" in select_sql


# ---------------------------------------------------------------------------
# Jobs are sent in batches of scorer_batch_size, not all at once
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jobs_batched_by_scorer_batch_size():
    # 25 jobs with batch_size=20 → 2 calls: chunk of 20, then chunk of 5
    all_ids = list(range(1, 26))
    db = _make_db(job_ids=all_ids)

    captured_chunks = []
    async def fake_scorer(db, chunk):
        captured_chunks.append(chunk)
        return {jid: True for jid in chunk}

    with (
        patch("app.pipeline.llm_scorer.score_jobs_by_ids", fake_scorer),
        patch("app.shared.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.scorer_batch_size = 20
        await _call_rescore_all(db)

    assert len(captured_chunks) == 2
    assert len(captured_chunks[0]) == 20
    assert len(captured_chunks[1]) == 5
    # All IDs covered, no duplicates
    assert sorted(sum(captured_chunks, [])) == all_ids


@pytest.mark.asyncio
async def test_single_batch_when_jobs_fit():
    # 5 jobs, batch_size=20 → exactly 1 call
    db = _make_db(job_ids=[1, 2, 3, 4, 5])

    captured_chunks = []
    async def fake_scorer(db, chunk):
        captured_chunks.append(chunk)
        return {jid: True for jid in chunk}

    with (
        patch("app.pipeline.llm_scorer.score_jobs_by_ids", fake_scorer),
        patch("app.shared.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.scorer_batch_size = 20
        await _call_rescore_all(db)

    assert len(captured_chunks) == 1
    assert captured_chunks[0] == [1, 2, 3, 4, 5]
