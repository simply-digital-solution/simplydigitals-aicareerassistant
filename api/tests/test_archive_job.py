"""
Unit tests for the archive job endpoint logic in app/modules/agents/router.py.

Tests the archive_job function in isolation: mocking DB and auth.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id: int = 1):
    u = MagicMock()
    u.id = user_id
    return u


def _db_with_job(found: bool = True):
    """Mock DB where SELECT returns a row (found=True) or None (found=False)."""
    db = AsyncMock()
    select_result = MagicMock()
    select_result.fetchone.return_value = (1,) if found else None
    db.execute.return_value = select_result
    return db


def _db_with_job_then_update():
    """Mock DB: first execute (SELECT) finds a row, second execute (UPDATE) succeeds."""
    db = AsyncMock()
    select_result = MagicMock()
    select_result.fetchone.return_value = (1,)
    db.execute.return_value = select_result
    return db


# ---------------------------------------------------------------------------
# Import the function under test
# ---------------------------------------------------------------------------

from app.modules.agents.router import archive_job


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_archive_job_success():
    """Happy path: job exists for user → archived, commit called."""
    db = _db_with_job_then_update()
    user = _make_user(1)

    await archive_job(job_id=42, current_user=user, db=db)

    assert db.execute.call_count == 2  # SELECT + UPDATE
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_archive_job_not_found_raises_404():
    """Job not found for user → HTTPException 404."""
    db = _db_with_job(found=False)
    user = _make_user(1)

    with pytest.raises(HTTPException) as exc_info:
        await archive_job(job_id=99, current_user=user, db=db)

    assert exc_info.value.status_code == 404
    # UPDATE should NOT have been called
    assert db.execute.call_count == 1


@pytest.mark.asyncio
async def test_archive_job_wrong_user_raises_404():
    """Job belonging to another user is not visible → 404, not 403."""
    db = _db_with_job(found=False)  # WHERE user_id=:uid returns nothing
    user = _make_user(user_id=999)

    with pytest.raises(HTTPException) as exc_info:
        await archive_job(job_id=1, current_user=user, db=db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_archive_job_is_idempotent():
    """Archiving an already-archived job succeeds (UPDATE runs, no error)."""
    db = _db_with_job_then_update()  # SELECT still returns a row even if archived=1
    user = _make_user(1)

    await archive_job(job_id=42, current_user=user, db=db)

    db.commit.assert_called_once()
