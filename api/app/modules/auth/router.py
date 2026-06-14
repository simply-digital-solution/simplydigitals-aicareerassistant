from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.shared.database import get_db
from app.shared.models import User

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
    return user
