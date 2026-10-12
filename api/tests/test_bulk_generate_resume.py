"""
Unit tests for POST /research/jobs/bulk-generate-resume
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


async def _call_bulk_generate(job_ids, db, user_id=1):
    from app.modules.agents.router import bulk_generate_resumes, BulkGenerateResumeRequest
    user = MagicMock()
    user.id = user_id
    body = BulkGenerateResumeRequest(job_ids=job_ids)
    return await bulk_generate_resumes(body=body, current_user=user, db=db)


def _make_db(owned_ids=None):
    db = AsyncMock()
    owned_result = MagicMock()
    owned_result.fetchall.return_value = [(jid,) for jid in (owned_ids or [])]
    db.execute.side_effect = [owned_result]
    return db


# ---------------------------------------------------------------------------
# No owned jobs → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_owned_jobs_raises_404():
    db = _make_db(owned_ids=[])
    with pytest.raises(HTTPException) as exc:
        await _call_bulk_generate([1, 2], db)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Happy path — returns results dict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_results_dict():
    db = _make_db(owned_ids=[1, 2])
    with patch("app.pipeline.resume_generator.generate_resumes_for_jobs",
               AsyncMock(return_value={1: True, 2: True})):
        result = await _call_bulk_generate([1, 2], db)
    assert result["results"] == {1: True, 2: True}


# ---------------------------------------------------------------------------
# Ownership filter — unowned IDs dropped silently
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_only_owned_ids_sent_to_generator():
    captured = {}

    async def fake_generator(db, job_ids, user_id):
        captured["job_ids"] = job_ids
        return {jid: True for jid in job_ids}

    db = _make_db(owned_ids=[1])

    with patch("app.pipeline.resume_generator.generate_resumes_for_jobs", fake_generator):
        await _call_bulk_generate([1, 99], db)  # 99 not owned

    assert captured["job_ids"] == [1]


# ---------------------------------------------------------------------------
# Ownership query — job_postings has no user_id column; ownership must be
# checked via a join to user_job_postings, not a direct WHERE user_id filter
# (that filter previously caused asyncpg.UndefinedColumnError on every call)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ownership_query_joins_user_job_postings_not_direct_user_id():
    db = _make_db(owned_ids=[1])
    with patch("app.pipeline.resume_generator.generate_resumes_for_jobs",
               AsyncMock(return_value={1: True})):
        await _call_bulk_generate([1], db)

    owned_sql = db.execute.call_args_list[0].args[0].text
    assert "user_job_postings" in owned_sql
    assert "WHERE user_id = :uid" not in owned_sql


# ---------------------------------------------------------------------------
# Partial failure — some False results returned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partial_failure_in_results():
    db = _make_db(owned_ids=[1, 2, 3])
    with patch("app.pipeline.resume_generator.generate_resumes_for_jobs",
               AsyncMock(return_value={1: True, 2: False, 3: True})):
        result = await _call_bulk_generate([1, 2, 3], db)
    assert result["results"][2] is False
    assert result["results"][1] is True
