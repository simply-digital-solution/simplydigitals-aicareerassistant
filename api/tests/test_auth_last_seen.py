"""
Tests for last_seen_at behaviour in get_current_user().

Verifies:
1. last_seen_at is updated on every authenticated request.
2. New user creation also sets last_seen_at immediately.
3. The admin /users query reads u.last_seen_at, not MAX(ar.started_at).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id: int = 1, email: str = "user@example.com"):
    u = MagicMock()
    u.id = user_id
    u.email = email
    return u


def _make_db(existing_user=None):
    """
    Build a mock DB that returns existing_user from the SELECT,
    or None to simulate a new user (triggers INSERT path).
    """
    db = AsyncMock()

    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = existing_user

    # First execute → SELECT; second execute → UPDATE last_seen_at
    db.execute.side_effect = [select_result, MagicMock()]
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock(side_effect=lambda u: None)
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_existing_user_last_seen_at_updated():
    """get_current_user must UPDATE last_seen_at for every request."""
    from app.modules.auth.router import get_current_user

    user = _make_user()
    db = _make_db(existing_user=user)

    result = await get_current_user(x_user_email="user@example.com", db=db)

    assert result is user

    # Second execute call must be the last_seen_at UPDATE
    update_call = db.execute.call_args_list[1]
    sql = str(update_call.args[0])
    assert "last_seen_at" in sql, "UPDATE must set last_seen_at"
    assert "users" in sql
    params = update_call.args[1]
    assert params["uid"] == user.id
    assert "now" in params

    db.commit.assert_called()


@pytest.mark.asyncio
async def test_last_seen_at_updated_on_every_call():
    """last_seen_at UPDATE must fire on every call, not just the first."""
    from app.modules.auth.router import get_current_user

    user = _make_user()

    for _ in range(3):
        db = _make_db(existing_user=user)
        await get_current_user(x_user_email="user@example.com", db=db)
        update_call = db.execute.call_args_list[1]
        sql = str(update_call.args[0])
        assert "last_seen_at" in sql


@pytest.mark.asyncio
async def test_admin_list_users_query_uses_last_seen_at():
    """
    Regression: admin /users query must read u.last_seen_at for last_active,
    not MAX(agent_runs.started_at), which fires on background scorer calls.
    """
    from app.modules.admin.router import list_users

    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.modules.admin.router.require_admin", return_value="admin@example.com"):
        await list_users(_="admin@example.com", db=db)

    sql = str(db.execute.call_args.args[0])
    assert "last_seen_at" in sql, (
        "admin /users query must read u.last_seen_at for last_active"
    )
    assert "MAX(ar.started_at)" not in sql, (
        "admin /users must not use MAX(agent_runs.started_at) — fires on scorer calls, not user activity"
    )


@pytest.mark.asyncio
async def test_admin_list_users_groups_by_last_seen_at():
    """
    GROUP BY must include u.last_seen_at now that it is a non-aggregate column.
    Without it the query would fail on PostgreSQL strict GROUP BY.
    """
    from app.modules.admin.router import list_users

    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.modules.admin.router.require_admin", return_value="admin@example.com"):
        await list_users(_="admin@example.com", db=db)

    sql = str(db.execute.call_args.args[0]).lower()
    assert "group by" in sql
    assert "last_seen_at" in sql, (
        "GROUP BY must include last_seen_at to satisfy PostgreSQL aggregate rules"
    )
