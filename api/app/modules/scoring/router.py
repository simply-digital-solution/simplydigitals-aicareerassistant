from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.router import get_current_user
from app.pipeline.llm_scorer import _get_scorings_today, _get_daily_limit
from app.shared.database import get_db

router = APIRouter(prefix="/api/v1/scoring", tags=["scoring"])


@router.get("/usage")
async def get_scoring_usage(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    daily_limit = await _get_daily_limit(db, current_user.id)
    jobs_scored_today = await _get_scorings_today(db, current_user.id)
    return {
        "jobs_scored_today": jobs_scored_today,
        "daily_limit": daily_limit,
        "remaining": max(0, daily_limit - jobs_scored_today),
    }
