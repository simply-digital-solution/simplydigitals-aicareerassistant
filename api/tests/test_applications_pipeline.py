"""
Unit tests for move_pipeline and kanban endpoints in applications/router.py
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def _make_user(user_id=1):
    user = MagicMock()
    user.id = user_id
    return user


def _make_app(app_id=1, user_id=1, status="selected", status_updated_at=None):
    app = MagicMock()
    app.id = app_id
    app.user_id = user_id
    app.status = status
    app.applied_at = None
    app.status_updated_at = status_updated_at
    app.company_name = "Acme"
    app.role_title = "Engineer"
    app.job_description = None
    app.jd_summary = None
    app.source_url = None
    app.source = "manual"
    app.fit_score = None
    app.deadline = None
    app.notes = None
    app.job_posting_id = None
    app.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    app.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return app


# ---------------------------------------------------------------------------
# move_pipeline — sets status_updated_at on every status change
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_sets_status_updated_at():
    from app.modules.applications.router import move_pipeline
    from app.modules.applications.schemas import PipelineMoveRequest

    app = _make_app(status="selected")
    db = AsyncMock()

    with patch("app.modules.applications.router._get_or_404", AsyncMock(return_value=app)):
        body = PipelineMoveRequest(application_id=1, new_status="applied")
        await move_pipeline(body=body, current_user=_make_user(), db=db)

    assert app.status == "applied"
    assert app.status_updated_at is not None
    assert isinstance(app.status_updated_at, datetime)


@pytest.mark.asyncio
async def test_move_sets_applied_at_when_status_is_applied():
    from app.modules.applications.router import move_pipeline
    from app.modules.applications.schemas import PipelineMoveRequest

    app = _make_app(status="selected")
    db = AsyncMock()

    with patch("app.modules.applications.router._get_or_404", AsyncMock(return_value=app)):
        body = PipelineMoveRequest(application_id=1, new_status="applied")
        await move_pipeline(body=body, current_user=_make_user(), db=db)

    assert app.applied_at is not None


@pytest.mark.asyncio
async def test_move_does_not_overwrite_applied_at_if_already_set():
    from datetime import date
    from app.modules.applications.router import move_pipeline
    from app.modules.applications.schemas import PipelineMoveRequest

    app = _make_app(status="selected")
    original_date = date(2026, 3, 1)
    app.applied_at = original_date
    db = AsyncMock()

    with patch("app.modules.applications.router._get_or_404", AsyncMock(return_value=app)):
        body = PipelineMoveRequest(application_id=1, new_status="applied")
        await move_pipeline(body=body, current_user=_make_user(), db=db)

    assert app.applied_at == original_date


@pytest.mark.asyncio
async def test_move_invalid_status_raises_400():
    from fastapi import HTTPException
    from app.modules.applications.router import move_pipeline
    from app.modules.applications.schemas import PipelineMoveRequest

    db = AsyncMock()
    body = PipelineMoveRequest(application_id=1, new_status="nonexistent")

    with pytest.raises(HTTPException) as exc:
        await move_pipeline(body=body, current_user=_make_user(), db=db)

    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# kanban — ordered by status_updated_at DESC
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kanban_orders_by_status_updated_at_desc():
    from app.modules.applications.router import get_pipeline

    older = _make_app(app_id=1, status="selected",
                      status_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    newer = _make_app(app_id=2, status="selected",
                      status_updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc))

    db = AsyncMock()
    result = MagicMock()
    # API returns apps ordered DESC already — simulate backend returning newer first
    result.scalars.return_value.all.return_value = [newer, older]
    db.execute.return_value = result

    board = await get_pipeline(current_user=_make_user(), db=db)

    selected = board["selected"]
    assert selected[0].id == 2  # newer first
    assert selected[1].id == 1


@pytest.mark.asyncio
async def test_kanban_groups_by_status():
    from app.modules.applications.router import get_pipeline

    app_selected = _make_app(app_id=1, status="selected")
    app_applied = _make_app(app_id=2, status="applied")

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [app_selected, app_applied]
    db.execute.return_value = result

    board = await get_pipeline(current_user=_make_user(), db=db)

    assert any(a.id == 1 for a in board["selected"])
    assert any(a.id == 2 for a in board["applied"])
