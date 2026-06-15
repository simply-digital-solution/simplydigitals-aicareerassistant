"""
Unit tests for POST /research/jobs/{job_id}/rescore
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


async def _call_rescore(job_id: int, db, user_id: int = 1):
    from app.modules.agents.router import rescore_job
    user = MagicMock()
    user.id = user_id
    return await rescore_job(job_id=job_id, current_user=user, db=db)


def _db_with_job(found: bool = True):
    db = AsyncMock()
    select_result = MagicMock()
    select_result.fetchone.return_value = (1,) if found else None
    update_result = MagicMock()
    db.execute.side_effect = [select_result, update_result]
    return db


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rescore_resets_score_fields():
    db = _db_with_job(found=True)

    await _call_rescore(job_id=1, db=db)

    db.commit.assert_called_once()
    update_sql = db.execute.call_args_list[1].args[0].text
    assert "scored" in update_sql
    assert "fit_score" in update_sql
    assert "scoring_breakdown" in update_sql


@pytest.mark.asyncio
async def test_rescore_raises_404_when_not_found():
    db = _db_with_job(found=False)

    with pytest.raises(HTTPException) as exc_info:
        await _call_rescore(job_id=999, db=db)

    assert exc_info.value.status_code == 404
    db.commit.assert_not_called()
