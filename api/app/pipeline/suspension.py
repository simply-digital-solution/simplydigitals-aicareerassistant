"""
Inactivity suspension logic.

A user is suspended when they have had zero job selections AND zero
job applications in the last INACTIVITY_DAYS days.  Suspended users
are excluded from both scoring and scraping.

Called daily by the scheduler and exposed via admin endpoints.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

INACTIVITY_DAYS = 7


async def suspend_inactive_users(db: AsyncSession) -> list[int]:
    """
    Find users with no activity in the last INACTIVITY_DAYS days and set
    scoring_suspended = 1.  Returns list of newly suspended user IDs.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=INACTIVITY_DAYS)).isoformat()

    # Users who have had any selection (application created) or application
    # submitted in the last 7 days
    active_result = await db.execute(text("""
        SELECT DISTINCT user_id FROM applications
        WHERE created_at >= :cutoff
           OR (status = 'applied' AND applied_at >= :cutoff_date)
    """), {"cutoff": cutoff, "cutoff_date": cutoff[:10]})
    active_ids = {row[0] for row in active_result.fetchall()}

    # Users who are not already suspended and not in the active set
    all_result = await db.execute(text("""
        SELECT id FROM users
        WHERE scoring_suspended = 0
    """))
    all_ids = [row[0] for row in all_result.fetchall()]

    # Only suspend users who have a profile (i.e. have used the app)
    # and are not in the active set
    to_suspend = []
    for uid in all_ids:
        if uid in active_ids:
            continue
        # Check user has a profile (has actually used the system)
        profile_result = await db.execute(
            text("SELECT 1 FROM profiles WHERE user_id = :uid"), {"uid": uid}
        )
        if not profile_result.first():
            continue
        to_suspend.append(uid)

    if to_suspend:
        # SQLite doesn't support tuple binding for IN — use explicit placeholders
        placeholders = ",".join(str(uid) for uid in to_suspend)
        await db.execute(
            text(f"UPDATE users SET scoring_suspended = 1 WHERE id IN ({placeholders})")
        )
        await db.commit()
        logger.info("suspension: suspended %d user(s): %s", len(to_suspend), to_suspend)
    else:
        logger.info("suspension: no new users to suspend")

    return to_suspend


async def reactivate_user(db: AsyncSession, user_id: int) -> bool:
    """Clear suspension for a single user. Returns True if user existed."""
    result = await db.execute(
        text("SELECT id FROM users WHERE id = :uid"), {"uid": user_id}
    )
    if not result.first():
        return False
    await db.execute(
        text("UPDATE users SET scoring_suspended = 0 WHERE id = :uid"),
        {"uid": user_id},
    )
    await db.commit()
    logger.info("suspension: reactivated user_id=%d", user_id)
    return True
