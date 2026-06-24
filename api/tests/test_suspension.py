"""Tests for inactivity suspension logic."""
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_result(rows: list):
    r = MagicMock()
    r.fetchall.return_value = rows
    r.first.return_value = rows[0] if rows else None
    return r


def _make_db(active_user_ids: list[int], all_unsuspended_ids: list[int], has_profile_ids: set[int]):
    """
    suspend_inactive_users executes in this order:
      1. SELECT active user_ids (had activity)
      2. SELECT all unsuspended user_ids
      3+. For each unsuspended non-active user: SELECT profile check
      4. UPDATE ... (only if users to suspend)
    """
    db = AsyncMock()

    side_effects = [
        _make_result([(uid,) for uid in active_user_ids]),
        _make_result([(uid,) for uid in all_unsuspended_ids]),
    ]

    inactive_ids = [uid for uid in all_unsuspended_ids if uid not in set(active_user_ids)]
    for uid in inactive_ids:
        side_effects.append(_make_result([(1,)] if uid in has_profile_ids else []))

    # UPDATE result (if any suspensions happen)
    side_effects.append(_make_result([]))

    db.execute = AsyncMock(side_effect=side_effects)
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_suspends_inactive_user_with_profile():
    from app.pipeline.suspension import suspend_inactive_users

    db = _make_db(
        active_user_ids=[],
        all_unsuspended_ids=[1],
        has_profile_ids={1},
    )
    suspended = await suspend_inactive_users(db)
    assert suspended == [1]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_does_not_suspend_active_user():
    from app.pipeline.suspension import suspend_inactive_users

    db = _make_db(
        active_user_ids=[1],
        all_unsuspended_ids=[1],
        has_profile_ids={1},
    )
    suspended = await suspend_inactive_users(db)
    assert suspended == []
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_does_not_suspend_user_without_profile():
    from app.pipeline.suspension import suspend_inactive_users

    db = _make_db(
        active_user_ids=[],
        all_unsuspended_ids=[2],
        has_profile_ids=set(),
    )
    suspended = await suspend_inactive_users(db)
    assert suspended == []
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_suspends_only_inactive_among_mixed_users():
    from app.pipeline.suspension import suspend_inactive_users

    db = _make_db(
        active_user_ids=[1],
        all_unsuspended_ids=[1, 2],
        has_profile_ids={1, 2},
    )
    suspended = await suspend_inactive_users(db)
    assert suspended == [2]


@pytest.mark.asyncio
async def test_no_users_to_suspend_skips_commit():
    from app.pipeline.suspension import suspend_inactive_users

    db = _make_db(
        active_user_ids=[1, 2],
        all_unsuspended_ids=[1, 2],
        has_profile_ids={1, 2},
    )
    suspended = await suspend_inactive_users(db)
    assert suspended == []
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_account_not_returned_by_old_account_query():
    """
    Accounts created within INACTIVITY_DAYS are excluded by the SQL cutoff filter.
    Simulate this by returning an empty all_unsuspended_ids list (as the DB would).
    """
    from app.pipeline.suspension import suspend_inactive_users

    db = _make_db(
        active_user_ids=[],
        all_unsuspended_ids=[],   # DB returns nothing because new account filtered by created_at
        has_profile_ids={1},
    )
    suspended = await suspend_inactive_users(db)
    assert suspended == []
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_reactivate_existing_user():
    from app.pipeline.suspension import reactivate_user

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _make_result([(1,)]),  # SELECT user exists
        _make_result([]),      # UPDATE
    ])
    db.commit = AsyncMock()

    result = await reactivate_user(db, user_id=5)
    assert result is True
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reactivate_nonexistent_user():
    from app.pipeline.suspension import reactivate_user

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_result([]))
    db.commit = AsyncMock()

    result = await reactivate_user(db, user_id=999)
    assert result is False
    db.commit.assert_not_awaited()
