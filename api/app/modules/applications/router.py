import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Application
from app.modules.auth.router import get_current_user
from app.shared.database import get_db
from .schemas import ApplicationCreate, ApplicationResponse, ApplicationUpdate, PipelineMoveRequest

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])

VALID_STATUSES = {"selected", "applied", "interviewing", "offered", "rejected", "withdrawn", "archived"}


@router.get("/", response_model=list[ApplicationResponse])
async def list_applications(
    status: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Application).where(Application.user_id == current_user.id)
    if status:
        q = q.where(Application.status == status)
    q = q.order_by(Application.created_at.desc())
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", response_model=ApplicationResponse, status_code=201)
async def create_application(
    body: ApplicationCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = Application(user_id=current_user.id, **body.model_dump())
    db.add(app)
    await db.flush()
    if app.job_posting_id and not app.job_description:
        row = await db.execute(
            text("SELECT description FROM job_postings WHERE id = :jid"),
            {"jid": app.job_posting_id},
        )
        desc = row.scalar_one_or_none()
        if desc:
            app.job_description = desc
            await db.flush()
    await db.refresh(app)
    return app


@router.get("/{app_id}", response_model=ApplicationResponse)
async def get_application(
    app_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await _get_or_404(db, app_id, current_user.id)
    return app


@router.patch("/{app_id}", response_model=ApplicationResponse)
async def update_application(
    app_id: int,
    body: ApplicationUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await _get_or_404(db, app_id, current_user.id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(app, field, value)
    await db.flush()
    await db.refresh(app)
    return app


@router.delete("/{app_id}", status_code=204)
async def delete_application(
    app_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await _get_or_404(db, app_id, current_user.id)
    await db.delete(app)


# ---------------------------------------------------------------------------
# Pipeline (tracker)
# ---------------------------------------------------------------------------

@router.get("/pipeline/kanban")
async def get_pipeline(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns applications grouped by status for the Kanban board."""
    rows = await db.execute(
        text("""
            SELECT a.*
            FROM applications a
            JOIN user_job_postings ujp
              ON ujp.job_posting_id = a.job_posting_id
             AND ujp.user_id = a.user_id
             AND ujp.archived = false
            WHERE a.user_id = :uid
            ORDER BY a.status_updated_at DESC
        """),
        {"uid": current_user.id},
    )
    app_rows = [dict(r) for r in rows.mappings()]

    board: dict[str, list] = {s: [] for s in VALID_STATUSES}
    for row in app_rows:
        status = row["status"] if row["status"] in VALID_STATUSES else "selected"
        board[status].append(ApplicationResponse.model_validate(row))

    return board


@router.post("/pipeline/move", response_model=ApplicationResponse)
async def move_pipeline(
    body: PipelineMoveRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.new_status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status. Must be one of: {VALID_STATUSES}")
    app = await _get_or_404(db, body.application_id, current_user.id)
    app.status = body.new_status
    from datetime import date, datetime, timezone
    app.status_updated_at = datetime.now(timezone.utc)
    if body.new_status == 'applied' and not app.applied_at:
        app.applied_at = date.today()
    if app.job_posting_id and not app.job_description:
        row = await db.execute(
            text("SELECT description FROM job_postings WHERE id = :jid"),
            {"jid": app.job_posting_id},
        )
        desc = row.scalar_one_or_none()
        if desc:
            app.job_description = desc
    await db.flush()
    await db.refresh(app)
    return app


@router.get("/pipeline/export")
async def export_csv(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Application)
        .where(Application.user_id == current_user.id)
        .order_by(Application.created_at.desc())
    )
    apps = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "company", "role", "status", "fit_score", "applied_at", "deadline", "source_url"])
    for app in apps:
        writer.writerow([
            app.id, app.company_name, app.role_title, app.status,
            app.fit_score, app.applied_at, app.deadline, app.source_url,
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tracked_apps.csv"},
    )


async def _get_or_404(db: AsyncSession, app_id: int, user_id: int) -> Application:
    result = await db.execute(
        select(Application).where(Application.id == app_id, Application.user_id == user_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "Application not found")
    return app
