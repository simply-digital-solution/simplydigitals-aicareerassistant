from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.router import get_current_user
from app.shared.database import get_db
from app.pipeline.suspension import suspend_inactive_users, reactivate_user

router = APIRouter(prefix="/api/v1", tags=["admin"])


@router.get("/me/status")
async def get_my_status(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return account status for the current user."""
    result = await db.execute(
        text("SELECT scoring_suspended FROM users WHERE id = :uid"),
        {"uid": current_user.id},
    )
    row = result.first()
    return {"scoring_suspended": bool(row[0]) if row else False}


@router.post("/admin/suspend-inactive")
async def run_suspend_inactive(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger the inactivity suspension check."""
    suspended = await suspend_inactive_users(db)
    return {"suspended_count": len(suspended), "suspended_user_ids": suspended}


@router.post("/admin/reactivate/{user_id}")
async def run_reactivate_user(
    user_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a suspended user by ID."""
    found = await reactivate_user(db, user_id)
    if not found:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"reactivated": True, "user_id": user_id}
