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


def _make_opp(job_id=1):
    from app.shared.schemas import JobOpportunity
    return JobOpportunity(
        job_id=job_id, role="Engineer", company="Co", link="",
        fit_score=0.8, reasons=["r1", "r2", "r3"], risks=["k1", "k2", "k3"],
        key_keywords=["kw"], inferred_industries=["Technology & Software"],
        scoring_breakdown=[], recommendation="Apply.",
    )


def _db_with_job(found: bool = True):
    db = AsyncMock()
    # [0] ownership SELECT
    select_result = MagicMock()
    select_result.fetchone.return_value = (1,) if found else None
    # [1] score_single_job: job SELECT
    job_select = MagicMock()
    job_select.mappings.return_value.first.return_value = {
        "id": 1, "user_id": 1, "title": "Eng", "company": "Co",
        "url": "", "description": "", "inferred_industries": "[]",
    } if found else None
    # [2] score_single_job: application status check (no advanced status)
    app_check = MagicMock()
    app_check.fetchone.return_value = None
    # [3] score_single_job: daily scoring usage check (0 = under limit)
    usage_check = MagicMock()
    usage_check.fetchone.return_value = (0,)
    # [4] score_single_job: rescoring=1 UPDATE
    rescoring_update = MagicMock()
    # [5] score_single_job: feedback SELECT
    feedback_select = MagicMock()
    feedback_select.mappings.return_value.all.return_value = []
    # [6] score write UPDATE (_write_score)
    score_update = MagicMock()
    # [7] _increment_scorings_today INSERT
    increment_result = MagicMock()
    # [8] final SELECT for response
    final_select = MagicMock()
    final_select.mappings.return_value.first.return_value = {"id": 1} if found else None

    db.execute.side_effect = [
        select_result,
        job_select, app_check, usage_check, rescoring_update, feedback_select,
        score_update, increment_result, final_select,
    ]
    return db


# ---------------------------------------------------------------------------
# Old scores are preserved — no pre-reset before scoring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rescore_does_not_wipe_scores_before_call():
    from app.shared.schemas import ResearchOutput
    db = _db_with_job(found=True)
    result = ResearchOutput(opportunities=[_make_opp(job_id=1)])

    with (
        patch("app.pipeline.llm_scorer._load_profile", AsyncMock(return_value={})),
        patch("app.pipeline.llm_scorer.run_research_agent", AsyncMock(return_value=(result, {}))),
    ):
        await _call_rescore(job_id=1, db=db)

    db.commit.assert_called()
    # 9 execute calls total — no pre-reset UPDATE before ownership check
    assert db.execute.call_count == 9
    # [1] is score_single_job's job SELECT, not a reset
    call1_sql = db.execute.call_args_list[1].args[0].text
    assert "SELECT" in call1_sql
    assert "scored = 0" not in call1_sql


# ---------------------------------------------------------------------------
# 404 when job not owned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rescore_raises_404_when_not_found():
    db = _db_with_job(found=False)

    with pytest.raises(HTTPException) as exc_info:
        await _call_rescore(job_id=999, db=db)

    assert exc_info.value.status_code == 404
    db.commit.assert_not_called()
