from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.shared.database import get_db
from app.shared.models import User
from app.shared.sql_compat import now_utc

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


async def get_current_user(
    x_user_email: str = Header(..., alias="X-User-Email"),
    db: AsyncSession = Depends(get_db),
):
    if not x_user_email or "@" not in x_user_email:
        raise HTTPException(status_code=400, detail="X-User-Email header must be a valid email")
    result = await db.execute(select(User).where(User.email == x_user_email))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email=x_user_email, hashed_password="")
        db.add(user)
        await db.commit()
        await db.refresh(user)

    await db.execute(
        text("UPDATE users SET last_seen_at = :now WHERE id = :uid"),
        {"now": now_utc(), "uid": user.id},
    )
    await db.commit()
    return user
