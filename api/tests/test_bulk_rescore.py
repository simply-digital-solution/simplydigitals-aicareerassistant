"""
Unit tests for POST /research/jobs/bulk-rescore
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


async def _call_bulk_rescore(job_ids, db, user_id=1):
    from app.modules.agents.router import bulk_rescore_jobs
    from app.modules.agents.router import BulkRescoreRequest
    user = MagicMock()
    user.id = user_id
    body = BulkRescoreRequest(job_ids=job_ids)
    return await bulk_rescore_jobs(body=body, current_user=user, db=db)


def _make_db(owned_ids=None, final_rows=None):
    db = AsyncMock()

    # [0] ownership SELECT
    owned_result = MagicMock()
    owned_result.fetchall.return_value = [(jid,) for jid in (owned_ids or [])]

    # [1] reset UPDATE
    reset_result = MagicMock()

    # [2] final SELECT
    final_result = MagicMock()
    final_result.mappings.return_value.all.return_value = final_rows or []

    db.execute.side_effect = [owned_result, reset_result, final_result]
    return db


# ---------------------------------------------------------------------------
# No owned jobs → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_owned_jobs_raises_404():
    db = _make_db(owned_ids=[])
    with pytest.raises(HTTPException) as exc:
        await _call_bulk_rescore([1, 2], db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Happy path — returns updated jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_updated_jobs():
    final_rows = [
        {"id": 1, "title": "Eng", "fit_score": 0.9},
        {"id": 2, "title": "PM",  "fit_score": 0.75},
    ]
    db = _make_db(owned_ids=[1, 2], final_rows=final_rows)

    with patch("app.pipeline.llm_scorer.score_jobs_by_ids", AsyncMock(return_value={1: True, 2: True})):
        result = await _call_bulk_rescore([1, 2], db)

    assert len(result["jobs"]) == 2
    assert result["jobs"][0]["id"] == 1


# ---------------------------------------------------------------------------
# Ownership filter — only owned IDs sent to scorer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_owned_ids_scored():
    captured = {}

    async def fake_scorer(db, job_ids):
        captured["job_ids"] = job_ids
        return {jid: True for jid in job_ids}

    db = _make_db(owned_ids=[1], final_rows=[{"id": 1, "title": "Eng"}])

    with patch("app.pipeline.llm_scorer.score_jobs_by_ids", fake_scorer):
        await _call_bulk_rescore([1, 99], db)  # 99 not owned

    assert captured["job_ids"] == [1]


# ---------------------------------------------------------------------------
# Reset fields called before scoring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_called_before_score():
    db = _make_db(owned_ids=[1, 2], final_rows=[])

    with patch("app.pipeline.llm_scorer.score_jobs_by_ids", AsyncMock(return_value={})):
        await _call_bulk_rescore([1, 2], db)

    # commit called after reset (index 1 is reset UPDATE)
    reset_sql = db.execute.call_args_list[1].args[0].text
    assert "scored = 0" in reset_sql
    assert "fit_score = NULL" in reset_sql
