from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.router import get_current_user
from app.shared.database import get_db
from app.shared.sql_compat import months_ago

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])

FIT_THRESHOLD = 0.7


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def _fill_days(rows: list[dict], key: str, days: int) -> list[dict]:
    """Return a dense list of {date, count} for the last `days` days, filling 0s."""
    lookup = {r[key]: r["count"] for r in rows}
    today = date.today()
    return [
        {key: (today - timedelta(days=days - 1 - i)).isoformat(),
         "count": lookup.get((today - timedelta(days=days - 1 - i)).isoformat(), 0)}
        for i in range(days)
    ]


def _fill_months(rows: list[dict], months: int) -> list[dict]:
    """Return a dense list of {month, count} for the last `months` months."""
    lookup = {r["month"]: r["count"] for r in rows}
    today = date.today()
    result = []
    for i in range(months - 1, -1, -1):
        # go back i months from current month
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        month_str = f"{y}-{m:02d}"
        result.append({"month": month_str, "count": lookup.get(month_str, 0)})
    return result


@router.get("/dashboard")
async def get_dashboard_stats(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = current_user.id
    since = _days_ago(30)

    # 1. Jobs scored by AI per day (last 30 days)
    r1 = await db.execute(text("""
        SELECT date(scored_at) AS day, count(*) AS count
        FROM job_postings
        WHERE user_id = :uid AND scored = true AND scored_at >= :since
        GROUP BY day ORDER BY day
    """), {"uid": uid, "since": since})
    scored_by_day = _fill_days(
        [{"date": str(row.day), "count": row.count} for row in r1.fetchall()],
        "date", 30,
    )

    # 2. Jobs fit for profile per day (fit_score >= threshold, last 30 days)
    r2 = await db.execute(text("""
        SELECT date(scored_at) AS day, count(*) AS count
        FROM job_postings
        WHERE user_id = :uid AND fit_score >= :threshold AND scored_at >= :since
        GROUP BY day ORDER BY day
    """), {"uid": uid, "threshold": FIT_THRESHOLD, "since": since})
    fit_by_day = _fill_days(
        [{"date": str(row.day), "count": row.count} for row in r2.fetchall()],
        "date", 30,
    )

    # 3. Jobs selected per day — applications created in last 30 days
    r3 = await db.execute(text("""
        SELECT date(created_at) AS day, count(*) AS count
        FROM applications
        WHERE user_id = :uid AND created_at >= :since
        GROUP BY day ORDER BY day
    """), {"uid": uid, "since": since})
    selected_by_day = _fill_days(
        [{"date": str(row.day), "count": row.count} for row in r3.fetchall()],
        "date", 30,
    )

    # 4. Jobs applied per day (last 30 days)
    r4 = await db.execute(text("""
        SELECT date(applied_at) AS day, count(*) AS count
        FROM applications
        WHERE user_id = :uid AND status = 'applied' AND applied_at >= :since
        GROUP BY day ORDER BY day
    """), {"uid": uid, "since": since})
    applied_by_day = _fill_days(
        [{"date": str(row.day), "count": row.count} for row in r4.fetchall()],
        "date", 30,
    )

    # 5. Jobs called for interview per month (last 3 months)
    r5 = await db.execute(text(f"""
        SELECT TO_CHAR(status_updated_at, 'YYYY-MM') AS month, count(*) AS count
        FROM applications
        WHERE user_id = :uid AND status = 'interviewing'
          AND status_updated_at >= :since_months
        GROUP BY month ORDER BY month
    """), {"uid": uid, "since_months": months_ago(3)})
    interviews_by_month = _fill_months(
        [{"month": str(row.month), "count": row.count} for row in r5.fetchall()],
        3,
    )

    return {
        "scored_by_day":       scored_by_day,
        "fit_by_day":          fit_by_day,
        "selected_by_day":     selected_by_day,
        "applied_by_day":      applied_by_day,
        "interviews_by_month": interviews_by_month,
    }
