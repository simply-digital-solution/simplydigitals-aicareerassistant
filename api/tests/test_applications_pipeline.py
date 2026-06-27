"""
Unit tests for move_pipeline, create_application, and kanban endpoints in applications/router.py
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
# kanban helpers — raw SQL mapping rows
# ---------------------------------------------------------------------------

def _make_row(app_id=1, user_id=1, status="selected",
              status_updated_at=None, company_name="Acme", role_title="Engineer"):
    """Return a dict simulating a raw SQL mapping row from the kanban query."""
    return {
        "id": app_id,
        "user_id": user_id,
        "status": status,
        "company_name": company_name,
        "role_title": role_title,
        "job_description": None,
        "jd_summary": None,
        "source_url": None,
        "source": "manual",
        "fit_score": None,
        "deadline": None,
        "applied_at": None,
        "notes": None,
        "job_posting_id": None,
        "status_updated_at": status_updated_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }


def _make_kanban_db(rows: list[dict]):
    """Return an AsyncMock DB whose execute().mappings() returns the given rows."""
    db = AsyncMock()
    result = MagicMock()
    result.mappings.return_value = rows
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# kanban — ordered by status_updated_at DESC
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kanban_orders_by_status_updated_at_desc():
    from app.modules.applications.router import get_pipeline

    older_row = _make_row(app_id=1, status_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    newer_row = _make_row(app_id=2, status_updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc))

    # DB returns rows already ordered DESC (newer first)
    db = _make_kanban_db([newer_row, older_row])
    board = await get_pipeline(current_user=_make_user(), db=db)

    selected = board["selected"]
    assert selected[0].id == 2  # newer first
    assert selected[1].id == 1


# ---------------------------------------------------------------------------
# move_pipeline — job_description backfill from job_postings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_backfills_job_description_when_null():
    """Backfills job_description from job_postings when it is NULL and job_posting_id is set."""
    from app.modules.applications.router import move_pipeline
    from app.modules.applications.schemas import PipelineMoveRequest

    app = _make_app(status="selected")
    app.job_posting_id = 42
    app.job_description = None

    db = AsyncMock()
    desc_row = MagicMock()
    desc_row.scalar_one_or_none.return_value = "Full JD text from posting"
    db.execute.return_value = desc_row

    with patch("app.modules.applications.router._get_or_404", AsyncMock(return_value=app)):
        body = PipelineMoveRequest(application_id=1, new_status="applied")
        await move_pipeline(body=body, current_user=_make_user(), db=db)

    assert app.job_description == "Full JD text from posting"


@pytest.mark.asyncio
async def test_move_does_not_overwrite_existing_job_description():
    """Does not overwrite job_description when it is already set."""
    from app.modules.applications.router import move_pipeline
    from app.modules.applications.schemas import PipelineMoveRequest

    app = _make_app(status="selected")
    app.job_posting_id = 42
    app.job_description = "Existing JD"

    db = AsyncMock()

    with patch("app.modules.applications.router._get_or_404", AsyncMock(return_value=app)):
        body = PipelineMoveRequest(application_id=1, new_status="applied")
        await move_pipeline(body=body, current_user=_make_user(), db=db)

    # db.execute should not be called to fetch the posting description
    db.execute.assert_not_called()
    assert app.job_description == "Existing JD"


@pytest.mark.asyncio
async def test_move_skips_backfill_when_no_job_posting_id():
    """Does not attempt backfill when job_posting_id is None (manual application)."""
    from app.modules.applications.router import move_pipeline
    from app.modules.applications.schemas import PipelineMoveRequest

    app = _make_app(status="selected")
    app.job_posting_id = None
    app.job_description = None

    db = AsyncMock()

    with patch("app.modules.applications.router._get_or_404", AsyncMock(return_value=app)):
        body = PipelineMoveRequest(application_id=1, new_status="applied")
        await move_pipeline(body=body, current_user=_make_user(), db=db)

    db.execute.assert_not_called()
    assert app.job_description is None


@pytest.mark.asyncio
async def test_move_handles_missing_posting_description_gracefully():
    """Leaves job_description as None when job_postings row has no description."""
    from app.modules.applications.router import move_pipeline
    from app.modules.applications.schemas import PipelineMoveRequest

    app = _make_app(status="selected")
    app.job_posting_id = 99
    app.job_description = None

    db = AsyncMock()
    desc_row = MagicMock()
    desc_row.scalar_one_or_none.return_value = None
    db.execute.return_value = desc_row

    with patch("app.modules.applications.router._get_or_404", AsyncMock(return_value=app)):
        body = PipelineMoveRequest(application_id=1, new_status="applied")
        await move_pipeline(body=body, current_user=_make_user(), db=db)

    assert app.job_description is None


# ---------------------------------------------------------------------------
# create_application — job_description backfill from job_postings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_backfills_job_description_from_posting():
    """Backfills job_description from job_postings on create when not provided."""
    from app.modules.applications.router import create_application
    from app.modules.applications.schemas import ApplicationCreate

    db = AsyncMock()

    # First execute call is for the backfill SELECT; second comes from refresh
    desc_row = MagicMock()
    desc_row.scalar_one_or_none.return_value = "JD from posting"
    db.execute.return_value = desc_row

    created_app = MagicMock()
    created_app.job_posting_id = 7
    created_app.job_description = None

    # Capture the Application instance added to the session
    captured = {}

    def fake_add(obj):
        captured["app"] = obj
        obj.job_posting_id = 7
        obj.job_description = None

    db.add.side_effect = fake_add

    async def fake_flush():
        pass

    db.flush = AsyncMock(side_effect=fake_flush)

    async def fake_refresh(obj):
        pass

    db.refresh = AsyncMock(side_effect=fake_refresh)

    with patch("app.modules.applications.router.Application") as MockApp:
        MockApp.return_value = created_app
        body = ApplicationCreate(
            company_name="Acme", role_title="Engineer",
            job_posting_id=7, status="selected",
        )
        result = await create_application(body=body, current_user=_make_user(), db=db)

    assert created_app.job_description == "JD from posting"


@pytest.mark.asyncio
async def test_create_does_not_overwrite_provided_job_description():
    """Does not overwrite job_description when caller already provides it."""
    from app.modules.applications.router import create_application
    from app.modules.applications.schemas import ApplicationCreate

    db = AsyncMock()

    created_app = MagicMock()
    created_app.job_posting_id = 7
    created_app.job_description = "Caller-provided JD"

    db.add.return_value = None

    with patch("app.modules.applications.router.Application") as MockApp:
        MockApp.return_value = created_app
        body = ApplicationCreate(
            company_name="Acme", role_title="Engineer",
            job_posting_id=7, job_description="Caller-provided JD", status="selected",
        )
        await create_application(body=body, current_user=_make_user(), db=db)

    # execute should not be called for backfill
    db.execute.assert_not_called()
    assert created_app.job_description == "Caller-provided JD"


@pytest.mark.asyncio
async def test_create_skips_backfill_when_no_job_posting_id():
    """Does not query job_postings when job_posting_id is None."""
    from app.modules.applications.router import create_application
    from app.modules.applications.schemas import ApplicationCreate

    db = AsyncMock()

    created_app = MagicMock()
    created_app.job_posting_id = None
    created_app.job_description = None

    db.add.return_value = None

    with patch("app.modules.applications.router.Application") as MockApp:
        MockApp.return_value = created_app
        body = ApplicationCreate(
            company_name="Acme", role_title="Engineer", status="selected",
        )
        await create_application(body=body, current_user=_make_user(), db=db)

    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# kanban — grouped by status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kanban_groups_by_status():
    from app.modules.applications.router import get_pipeline

    row_selected = _make_row(app_id=1, status="selected")
    row_applied  = _make_row(app_id=2, status="applied")

    db = _make_kanban_db([row_selected, row_applied])
    board = await get_pipeline(current_user=_make_user(), db=db)

    assert any(a.id == 1 for a in board["selected"])
    assert any(a.id == 2 for a in board["applied"])


@pytest.mark.asyncio
async def test_kanban_excludes_archived_jobs():
    """
    Positive: kanban SQL JOINs user_job_postings with archived=false,
    so archived job postings do not appear in any column.
    """
    from app.modules.applications.router import get_pipeline

    # Only non-archived rows are returned by the DB (JOIN filters them out)
    row_active = _make_row(app_id=1, status="selected")
    db = _make_kanban_db([row_active])
    board = await get_pipeline(current_user=_make_user(), db=db)

    assert len(board["selected"]) == 1
    assert board["selected"][0].id == 1


@pytest.mark.asyncio
async def test_kanban_sql_joins_user_job_postings_with_archived_filter():
    """
    Regression: kanban query must JOIN user_job_postings with archived=false
    to match the Selected tab query — prevents inflated selected count.
    """
    from app.modules.applications.router import get_pipeline

    db = _make_kanban_db([])
    await get_pipeline(current_user=_make_user(), db=db)

    sql = str(db.execute.call_args_list[0].args[0])
    assert "user_job_postings" in sql
    assert "archived" in sql


@pytest.mark.asyncio
async def test_kanban_empty_board_returns_all_status_keys():
    """Positive: board always has all status keys even when no apps exist."""
    from app.modules.applications.router import get_pipeline, VALID_STATUSES

    db = _make_kanban_db([])
    board = await get_pipeline(current_user=_make_user(), db=db)

    assert set(board.keys()) == VALID_STATUSES
    assert all(v == [] for v in board.values())


@pytest.mark.asyncio
async def test_kanban_unknown_status_bucketed_into_selected():
    """Negative: application with unknown status falls back to 'selected' bucket."""
    from app.modules.applications.router import get_pipeline

    row = _make_row(app_id=5, status="unknown_future_status")
    db = _make_kanban_db([row])
    board = await get_pipeline(current_user=_make_user(), db=db)

    assert any(a.id == 5 for a in board["selected"])
