from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.database import get_db
from app.pipeline.suspension import suspend_inactive_users, reactivate_user

ADMIN_EMAIL = "pandiri.vasu@gmail.com"

router = APIRouter(prefix="/api/v1", tags=["admin"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def require_admin(x_user_email: str = Header(..., alias="X-User-Email")) -> str:
    if x_user_email.strip().lower() != ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Admin access only.")
    return x_user_email


# ---------------------------------------------------------------------------
# Existing user-facing status endpoint (no admin gate)
# ---------------------------------------------------------------------------

async def _get_current_user_basic(x_user_email: str = Header(..., alias="X-User-Email")):
    if not x_user_email or "@" not in x_user_email:
        raise HTTPException(status_code=400, detail="X-User-Email header must be a valid email")
    return x_user_email


@router.get("/me/status")
async def get_my_status(
    x_user_email: str = Depends(_get_current_user_basic),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("SELECT scoring_suspended FROM users WHERE email = :email"),
        {"email": x_user_email},
    )
    row = result.first()
    return {"scoring_suspended": bool(row[0]) if row else False}


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class DailyCount(BaseModel):
    date: str
    count: int


class DailyTokens(BaseModel):
    date: str
    input_tokens: int
    output_tokens: int


class UserTokenDay(BaseModel):
    date: str
    email: str
    requests: int
    input_tokens: int
    output_tokens: int


class UserRow(BaseModel):
    id: int
    email: str
    created_at: str
    scoring_suspended: bool
    last_active: str | None
    total_llm_requests: int
    total_jobs: int


class AgentRunStats(BaseModel):
    date: str
    complete: int
    failed: int


class ScoringStats(BaseModel):
    date: str
    jobs_scored: int


# ---------------------------------------------------------------------------
# 1. Active users per day (distinct users from agent_runs.started_at)
# ---------------------------------------------------------------------------

@router.get("/admin/stats/users-active")
async def stats_users_active(
    days: int = 30,
    _: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[DailyCount]:
    rows = await db.execute(text("""
        SELECT DATE(started_at) AS day, COUNT(DISTINCT user_id) AS cnt
        FROM agent_runs
        WHERE started_at >= DATE('now', :offset)
        GROUP BY day
        ORDER BY day
    """), {"offset": f"-{days} days"})
    return [DailyCount(date=str(r[0]), count=r[1]) for r in rows.fetchall()]


# ---------------------------------------------------------------------------
# 2. LLM tokens per day (global, from budget_records)
# ---------------------------------------------------------------------------

@router.get("/admin/stats/llm-tokens")
async def stats_llm_tokens(
    days: int = 30,
    _: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[DailyTokens]:
    rows = await db.execute(text("""
        SELECT date,
               SUM(total_input_tokens)  AS inp,
               SUM(total_output_tokens) AS out
        FROM budget_records
        WHERE date >= DATE('now', :offset)
        GROUP BY date
        ORDER BY date
    """), {"offset": f"-{days} days"})
    return [DailyTokens(date=str(r[0]), input_tokens=r[1] or 0, output_tokens=r[2] or 0)
            for r in rows.fetchall()]


# ---------------------------------------------------------------------------
# 3. New jobs scraped per day (cross-user, from job_postings.scraped_at)
# ---------------------------------------------------------------------------

@router.get("/admin/stats/jobs-scraped")
async def stats_jobs_scraped(
    days: int = 30,
    _: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[DailyCount]:
    rows = await db.execute(text("""
        SELECT DATE(scraped_at) AS day, COUNT(*) AS cnt
        FROM job_postings
        WHERE scraped_at >= DATE('now', :offset)
        GROUP BY day
        ORDER BY day
    """), {"offset": f"-{days} days"})
    return [DailyCount(date=str(r[0]), count=r[1]) for r in rows.fetchall()]


# ---------------------------------------------------------------------------
# 4+5. LLM requests + tokens per user per day (from agent_runs)
# ---------------------------------------------------------------------------

@router.get("/admin/stats/llm-per-user")
async def stats_llm_per_user(
    days: int = 30,
    _: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[UserTokenDay]:
    rows = await db.execute(text("""
        SELECT DATE(ar.started_at) AS day,
               u.email,
               COUNT(*)                   AS requests,
               SUM(ar.input_tokens)       AS inp,
               SUM(ar.output_tokens)      AS out
        FROM agent_runs ar
        JOIN users u ON u.id = ar.user_id
        WHERE ar.started_at >= DATE('now', :offset)
        GROUP BY day, u.email
        ORDER BY day DESC, requests DESC
    """), {"offset": f"-{days} days"})
    return [
        UserTokenDay(
            date=str(r[0]), email=r[1],
            requests=r[2], input_tokens=r[3] or 0, output_tokens=r[4] or 0,
        )
        for r in rows.fetchall()
    ]


# ---------------------------------------------------------------------------
# 6. Agent run success / failure rate per day
# ---------------------------------------------------------------------------

@router.get("/admin/stats/agent-runs")
async def stats_agent_runs(
    days: int = 30,
    _: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AgentRunStats]:
    rows = await db.execute(text("""
        SELECT DATE(started_at) AS day,
               SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS ok,
               SUM(CASE WHEN status = 'failed'   THEN 1 ELSE 0 END) AS fail
        FROM agent_runs
        WHERE started_at >= DATE('now', :offset)
        GROUP BY day
        ORDER BY day
    """), {"offset": f"-{days} days"})
    return [AgentRunStats(date=str(r[0]), complete=r[1] or 0, failed=r[2] or 0)
            for r in rows.fetchall()]


# ---------------------------------------------------------------------------
# 7. Scoring activity per day
# ---------------------------------------------------------------------------

@router.get("/admin/stats/scoring")
async def stats_scoring(
    days: int = 30,
    _: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ScoringStats]:
    rows = await db.execute(text("""
        SELECT date, SUM(jobs_scored) AS total
        FROM daily_scoring_usage
        WHERE date >= DATE('now', :offset)
        GROUP BY date
        ORDER BY date
    """), {"offset": f"-{days} days"})
    return [ScoringStats(date=str(r[0]), jobs_scored=r[1] or 0)
            for r in rows.fetchall()]


# ---------------------------------------------------------------------------
# 8. User list with status + last active + usage totals
# ---------------------------------------------------------------------------

@router.get("/admin/users")
async def list_users(
    _: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[UserRow]:
    rows = await db.execute(text("""
        SELECT
            u.id,
            u.email,
            u.created_at,
            u.scoring_suspended,
            MAX(ar.started_at)         AS last_active,
            COUNT(ar.id)               AS total_llm_requests,
            COUNT(DISTINCT jp.id)      AS total_jobs
        FROM users u
        LEFT JOIN agent_runs ar ON ar.user_id = u.id
        LEFT JOIN job_postings jp ON jp.user_id = u.id
        GROUP BY u.id
        ORDER BY last_active DESC NULLS LAST
    """))
    result = []
    for r in rows.fetchall():
        result.append(UserRow(
            id=r[0],
            email=r[1],
            created_at=str(r[2]),
            scoring_suspended=bool(r[3]),
            last_active=str(r[4]) if r[4] else None,
            total_llm_requests=r[5] or 0,
            total_jobs=r[6] or 0,
        ))
    return result


# ---------------------------------------------------------------------------
# 9. Activate / suspend user
# ---------------------------------------------------------------------------

@router.post("/admin/users/{user_id}/activate")
async def activate_user(
    user_id: int,
    _: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    found = await reactivate_user(db, user_id)
    if not found:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"activated": True, "user_id": user_id}


@router.post("/admin/users/{user_id}/suspend")
async def suspend_user(
    user_id: int,
    _: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("UPDATE users SET scoring_suspended = 1 WHERE id = :uid"),
        {"uid": user_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="User not found.")
    await db.commit()
    return {"suspended": True, "user_id": user_id}


# ---------------------------------------------------------------------------
# 10. Trigger inactivity suspension (kept for backward compat)
# ---------------------------------------------------------------------------

@router.post("/admin/suspend-inactive")
async def run_suspend_inactive(
    _: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    suspended = await suspend_inactive_users(db)
    return {"suspended_count": len(suspended), "suspended_user_ids": suspended}


@router.post("/admin/cleanup/research-jobs")
async def run_research_job_cleanup(
    days: int = 30,
    _: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger deletion of stale research-only job postings."""
    from app.pipeline.job_cleanup import purge_stale_research_jobs
    deleted = await purge_stale_research_jobs(db, days=days)
    return {"deleted": deleted, "older_than_days": days}
